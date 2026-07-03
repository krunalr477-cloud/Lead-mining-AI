"""robots.txt fetch + cache + honoring (spec §8 "Respect robots.txt", §18).

We fetch ``/robots.txt`` once per host, cache the raw body in Redis for 24h, and
parse it with ``protego``. ``RobotsPolicy.allowed(path)`` answers per-path; a
missing / errored / unfetchable robots file means ALLOW (fail-open, the polite
default). Crawl-delay is honored, capped at 10s so a hostile file can't stall a
job. The fetch itself goes through the ctx-audited HTTP helper so even the
robots probe lands in Data_Source_Audit.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from protego import Protego

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["RobotsPolicy", "fetch_robots", "USER_AGENT"]

USER_AGENT = "LeadMineBot/1.0 (+contact)"
_ROBOTS_CACHE_TTL = 86_400  # 24h
_MAX_CRAWL_DELAY = 10.0


@dataclass(slots=True)
class RobotsPolicy:
    """Parsed robots policy for one host (or a permissive fail-open default)."""

    _parser: Protego | None
    crawl_delay: float | None

    @classmethod
    def allow_all(cls) -> RobotsPolicy:
        return cls(_parser=None, crawl_delay=None)

    def allowed(self, url: str) -> bool:
        if self._parser is None:
            return True
        return bool(self._parser.can_fetch(url, USER_AGENT))


def _cache_key(host: str) -> str:
    return f"crawl:robots:{host.lower()}"


async def fetch_robots(
    client: httpx.AsyncClient,
    scheme: str,
    host: str,
    ctx: SourceRunContext,
) -> RobotsPolicy:
    """Return the RobotsPolicy for ``host``, using a 24h Redis cache.

    Cache stores the raw robots body (or a sentinel for "no robots"). A network
    error or non-2xx/404 fetch fails open (allow all). Every live fetch is
    audited.
    """
    key = _cache_key(host)
    cached = None
    with contextlib.suppress(Exception):  # redis optional/best-effort
        cached = ctx.redis.get(key)

    if cached is not None:
        body = cached.decode() if isinstance(cached, bytes) else cached
        return _policy_from_body(body, host)

    robots_url = f"{scheme}://{host}/robots.txt"
    body = ""
    try:
        resp = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
        if resp.status_code == 200:
            body = resp.text[:512_000]  # cap: robots files are small
            ctx.audit(robots_url, status="ok", records_found=0)
        else:
            # 4xx/5xx (incl 404) => no rules => allow all.
            ctx.audit(robots_url, status=f"http_{resp.status_code}", records_found=0)
            body = ""
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        ctx.audit(robots_url, status="error", error=str(exc)[:200])
        body = ""

    with contextlib.suppress(Exception):  # pragma: no cover - best-effort cache
        ctx.redis.setex(key, _ROBOTS_CACHE_TTL, body)

    return _policy_from_body(body, host)


def _policy_from_body(body: str, host: str) -> RobotsPolicy:
    if not body.strip():
        return RobotsPolicy.allow_all()
    try:
        parser = Protego.parse(body)
    except Exception:  # pragma: no cover - malformed robots => allow
        return RobotsPolicy.allow_all()
    delay = parser.crawl_delay(USER_AGENT)
    capped = None
    if delay is not None:
        capped = min(float(delay), _MAX_CRAWL_DELAY)
    return RobotsPolicy(_parser=parser, crawl_delay=capped)
