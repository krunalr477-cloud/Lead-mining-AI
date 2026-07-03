"""Tiered async page fetch (spec §8 "Playwright for website crawling where
permitted", rate limits, caps).

Tier 1 — httpx (HTTP/2, honest User-Agent, 15s timeout). Fast path for the
static HTML the vast majority of firm sites serve.

Tier 2 — Playwright Chromium, used ONLY when Tier-1 output looks empty
(< 400 chars of visible text) or shows SPA markers (an app root with no server-
rendered content). Guarded: if Playwright isn't installed / can't launch, we
skip Tier 2 gracefully and return the Tier-1 result.

Politeness / safety:
- per-domain Redis token bucket ``rl:domain:{domain}`` at
  ``settings.crawler_per_domain_delay_seconds`` (via bucket_for_domain);
- 1 MB HTML cap, ``crawler_max_pages_per_domain`` page cap, 120s wall budget
  (enforced by the caller/CrawlBudget helper here).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.crawler.robots import USER_AGENT
from app.workers.rate_limit import bucket_for_domain

__all__ = ["FetchResult", "CrawlBudget", "PageFetcher", "playwright_available"]

_MAX_HTML_BYTES = 1_048_576  # 1 MB
_TIER1_TIMEOUT = 15.0
_SPA_MARKERS = (
    'id="root"',
    'id="app"',
    'id="__next"',
    "data-reactroot",
    "ng-app",
    "ng-version",
)
_MIN_TEXT_CHARS = 400
_DEFAULT_BUDGET_SECONDS = 120.0
_RL_MAX_WAIT = 15.0  # never block a single fetch longer than this on the bucket


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int
    html: str
    text_len: int
    tier: int  # 1 = httpx, 2 = playwright, 0 = failed
    ok: bool
    error: str | None = None
    escalated: bool = False


def playwright_available() -> bool:
    """True iff the async Playwright API can be imported (not whether a browser
    binary is installed — launch failures are handled at Tier 2)."""
    try:
        import playwright.async_api  # noqa: F401
    except Exception:
        return False
    return True


def _visible_text_len(html: str) -> int:
    """Cheap estimate of visible text length (strip tags, collapse space)."""
    import re

    without_scripts = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    stripped = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return len(" ".join(stripped.split()))


def _needs_escalation(html: str) -> bool:
    if _visible_text_len(html) < _MIN_TEXT_CHARS:
        return True
    low = html.lower()
    # SPA marker AND still very little text => likely client-rendered.
    return any(marker in low for marker in _SPA_MARKERS) and _visible_text_len(html) < 1200


class CrawlBudget:
    """Wall-clock + page-count budget for one domain crawl."""

    def __init__(self, max_pages: int, seconds: float = _DEFAULT_BUDGET_SECONDS) -> None:
        self.max_pages = max_pages
        self.deadline = time.monotonic() + seconds
        self.pages_fetched = 0

    def can_fetch(self) -> bool:
        return self.pages_fetched < self.max_pages and time.monotonic() < self.deadline

    def record(self) -> None:
        self.pages_fetched += 1


class PageFetcher:
    """Tiered fetcher bound to one httpx client + a per-domain rate limiter.

    Callers construct one per domain crawl and reuse the shared client. The
    fetcher enforces the per-domain token bucket, byte cap, and escalation; the
    caller enforces the page/time budget via ``CrawlBudget``.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        per_domain_delay: float | None = None,
        allow_playwright: bool = True,
    ) -> None:
        settings = get_settings()
        self.client = client
        self.per_domain_delay = (
            per_domain_delay
            if per_domain_delay is not None
            else settings.crawler_per_domain_delay_seconds
        )
        self.allow_playwright = allow_playwright

    async def _throttle(self, domain: str) -> None:
        """Block on the per-domain Redis token bucket (bounded wait)."""
        try:
            bucket = bucket_for_domain(domain, self.per_domain_delay)
        except Exception:
            return  # no redis in a unit context => no throttle
        waited = 0.0
        while not bucket.acquire(1):
            delay = min(bucket.suggested_delay() or self.per_domain_delay, _RL_MAX_WAIT - waited)
            if delay <= 0:
                break
            await asyncio.sleep(delay)
            waited += delay
            if waited >= _RL_MAX_WAIT:
                break

    async def fetch(self, url: str) -> FetchResult:
        """Fetch one page (Tier 1, escalating to Tier 2 when warranted)."""
        domain = urlparse(url).netloc.lower()
        await self._throttle(domain)

        tier1 = await self._fetch_httpx(url)
        if not tier1.ok:
            # Nothing to escalate from on a hard failure.
            return tier1

        if self.allow_playwright and _needs_escalation(tier1.html):
            tier2 = await self._fetch_playwright(url)
            if tier2 is not None and tier2.ok and tier2.text_len > tier1.text_len:
                tier2.escalated = True
                return tier2
            tier1.escalated = True  # we tried; record the attempt
        return tier1

    async def _fetch_httpx(self, url: str) -> FetchResult:
        try:
            resp = await self.client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            return FetchResult(url, 0, "", 0, tier=0, ok=False, error=str(exc)[:200])

        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and ctype:
            return FetchResult(url, resp.status_code, "", 0, tier=1, ok=False, error="non-html")

        raw = resp.content[:_MAX_HTML_BYTES]
        try:
            html = raw.decode(resp.encoding or "utf-8", errors="replace")
        except (LookupError, ValueError):
            html = raw.decode("utf-8", errors="replace")
        ok = 200 <= resp.status_code < 300
        return FetchResult(
            url,
            resp.status_code,
            html if ok else "",
            _visible_text_len(html) if ok else 0,
            tier=1,
            ok=ok,
            error=None if ok else f"http_{resp.status_code}",
        )

    async def _fetch_playwright(self, url: str) -> FetchResult | None:
        """Tier 2. Returns None if Playwright is unavailable/unlaunchable.

        Playwright is an OPTIONAL dependency: Tier 1 (httpx) handles most sites,
        and this method degrades gracefully when the package or its browser binary
        is absent. To enable JS-rendered fallback, install the chromium binary:

            uv run playwright install chromium
        """
        if not playwright_available():
            return None
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(user_agent=USER_AGENT)
                    await page.goto(
                        url, timeout=int(_TIER1_TIMEOUT * 1000), wait_until="networkidle"
                    )
                    html = await page.content()
                finally:
                    await browser.close()
        except Exception as exc:  # launch/nav failure => graceful skip
            return FetchResult(
                url, 0, "", 0, tier=0, ok=False, error=f"playwright: {str(exc)[:150]}"
            )
        html = html[:_MAX_HTML_BYTES]
        return FetchResult(url, 200, html, _visible_text_len(html), tier=2, ok=True, error=None)
