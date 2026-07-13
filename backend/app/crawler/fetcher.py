"""Tiered async page fetch (spec §8 "Playwright for website crawling where
permitted", rate limits, caps).

Tier 1 — httpx (HTTP/2, realistic browser User-Agent, 15s timeout), with a
retry ladder for TRANSIENT failures (DNS/connect/timeout/SSL/403/503): a flaky
network blip or a WAF challenge must not permanently mark a live site
unreachable (a real run falsely failed 87% of sites this way). SSL verification
failures get one retry through a verify=False client (recorded, not hidden).

Tier 2 — Playwright Chromium, used when Tier-1 output looks empty (< 400 chars
of visible text / SPA markers) OR when Tier 1 exhausted its ladder on a hard
failure — a real browser clears most WAF blocks. Budgeted per job via the
caller-supplied ``may_use_playwright`` callable. Guarded: if Playwright isn't
installed / can't launch, we skip Tier 2 gracefully.

UA policy: robots.txt is fetched AND evaluated under the LeadMineBot token
(compliance substance, see app/crawler/robots.py); page fetches use a standard
browser UA (``settings.crawler_browser_user_agent``) because bot-labeled UAs
are blanket-403'd by common hosts, which reads as false unreachability.

Politeness / safety:
- per-domain Redis token bucket ``rl:domain:{domain}`` at
  ``settings.crawler_per_domain_delay_seconds`` (via bucket_for_domain);
- 1 MB HTML cap, ``crawler_max_pages_per_domain`` page cap, 120s wall budget
  (enforced by the caller/CrawlBudget helper here).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import get_settings
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

# Failure kinds worth retrying: network blips and WAF-ish statuses.
_TRANSIENT_KINDS = frozenset(
    {"dns", "connect", "timeout", "ssl", "http_403", "http_503", "http_429", "http_5xx"}
)
# Kinds a REAL BROWSER can plausibly clear (WAF/bot blocks). DNS/connect
# failures would fail identically in Chromium — don't burn a launch on them.
_BROWSER_CLEARABLE_KINDS = frozenset({"http_403", "http_503", "http_429", "http_5xx"})
# Backoff before retry attempt N+1 (tests may monkeypatch to zeros).
_RETRY_BACKOFFS = (1.0, 3.0)


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
    # Classified failure kind (see _TRANSIENT_KINDS + http_4xx/non_html/playwright).
    error_kind: str | None = None
    # True when the page was only reachable with SSL verification disabled.
    ssl_insecure: bool = False


def _classify_httpx_error(exc: httpx.HTTPError) -> str:
    """Bucket an httpx exception into a retry-relevant failure kind."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    text = " ".join(str(part) for part in (exc, exc.__cause__ or "")).lower()
    if "certificate" in text or "ssl" in text or "tls" in text:
        return "ssl"
    if (
        "nodename nor servname" in text
        or "name or service not known" in text
        or "getaddrinfo" in text
        or "temporary failure in name resolution" in text
        or "name resolution" in text
    ):
        return "dns"
    return "connect"


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
        may_use_playwright: Callable[[], bool] | None = None,
        insecure_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.client = client
        self.per_domain_delay = (
            per_domain_delay
            if per_domain_delay is not None
            else settings.crawler_per_domain_delay_seconds
        )
        self.allow_playwright = allow_playwright
        # Per-job Playwright budget hook (Redis counter lives with the caller so
        # the fetcher stays transport-only). None => unbudgeted.
        self.may_use_playwright = may_use_playwright or (lambda: True)
        self._insecure_client = insecure_client
        self._owns_insecure_client = insecure_client is None

    def _insecure(self) -> httpx.AsyncClient:
        """Lazily-built verify=False client for the one-shot SSL-error retry."""
        if self._insecure_client is None:
            self._insecure_client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(_TIER1_TIMEOUT, connect=10.0),
                max_redirects=5,
                verify=False,
            )
        return self._insecure_client

    async def aclose(self) -> None:
        """Close the lazily-created insecure client (the main client is owned by
        the caller's context manager)."""
        if self._owns_insecure_client and self._insecure_client is not None:
            await self._insecure_client.aclose()
            self._insecure_client = None

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

    async def fetch(self, url: str, *, attempts: int | None = None) -> FetchResult:
        """Fetch one page through the retry ladder, escalating to Tier 2 when
        warranted (thin content on success, or a hard failure a real browser
        might clear). ``attempts`` overrides the configured ladder length —
        callers pass 1 for cheap probes (URL variants, sub-pages)."""
        domain = urlparse(url).netloc.lower()
        await self._throttle(domain)

        max_attempts = (
            attempts if attempts is not None else max(1, get_settings().crawler_fetch_attempts)
        )
        result: FetchResult | None = None
        for attempt in range(max_attempts):
            result = await self._fetch_httpx(url)
            if result.ok:
                break
            if result.error_kind == "ssl":
                # One shot through the verify=False client: many small-firm sites
                # have expired/mismatched certs that browsers click through.
                insecure = await self._fetch_httpx(url, insecure=True)
                if insecure.ok:
                    insecure.ssl_insecure = True
                    result = insecure
                    break
            if result.error_kind not in _TRANSIENT_KINDS:
                break
            if attempt < max_attempts - 1:
                await asyncio.sleep(_RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)])

        assert result is not None  # max_attempts >= 1

        if result.ok:
            if self.allow_playwright and _needs_escalation(result.html) and self.may_use_playwright():
                tier2 = await self._fetch_playwright(url)
                if tier2 is not None and tier2.ok and tier2.text_len > result.text_len:
                    tier2.escalated = True
                    return tier2
                result.escalated = True  # we tried; record the attempt
            return result

        # Hard failure after the ladder: a real browser clears most WAF blocks
        # (403/503/429) — final budgeted attempt. DNS/connect failures are not
        # escalated: Chromium shares the same network and would fail identically.
        if (
            self.allow_playwright
            and result.error_kind in _BROWSER_CLEARABLE_KINDS
            and self.may_use_playwright()
        ):
            tier2 = await self._fetch_playwright(url)
            if tier2 is not None and tier2.ok:
                tier2.escalated = True
                return tier2
        return result

    async def _fetch_httpx(self, url: str, *, insecure: bool = False) -> FetchResult:
        client = self._insecure() if insecure else self.client
        try:
            resp = await client.get(
                url,
                headers={"User-Agent": get_settings().crawler_browser_user_agent},
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            kind = _classify_httpx_error(exc)
            return FetchResult(
                url, 0, "", 0, tier=0, ok=False, error=str(exc)[:200], error_kind=kind
            )

        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and ctype:
            return FetchResult(
                url, resp.status_code, "", 0, tier=1, ok=False, error="non-html",
                error_kind="non_html",
            )

        raw = resp.content[:_MAX_HTML_BYTES]
        try:
            html = raw.decode(resp.encoding or "utf-8", errors="replace")
        except (LookupError, ValueError):
            html = raw.decode("utf-8", errors="replace")
        ok = 200 <= resp.status_code < 300
        if ok:
            error_kind = None
        elif resp.status_code in (403, 503, 429):
            error_kind = f"http_{resp.status_code}"
        elif resp.status_code >= 500:
            error_kind = "http_5xx"
        else:
            error_kind = "http_4xx"
        return FetchResult(
            url,
            resp.status_code,
            html if ok else "",
            _visible_text_len(html) if ok else 0,
            tier=1,
            ok=ok,
            error=None if ok else f"http_{resp.status_code}",
            error_kind=error_kind,
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
                    # Chromium's own UA — a real browser fingerprint clears WAFs
                    # that blanket-block labeled bots.
                    page = await browser.new_page()
                    await page.goto(
                        url, timeout=int(_TIER1_TIMEOUT * 1000), wait_until="networkidle"
                    )
                    html = await page.content()
                finally:
                    await browser.close()
        except Exception as exc:  # launch/nav failure => graceful skip
            return FetchResult(
                url, 0, "", 0, tier=0, ok=False,
                error=f"playwright: {str(exc)[:150]}", error_kind="playwright",
            )
        html = html[:_MAX_HTML_BYTES]
        return FetchResult(url, 200, html, _visible_text_len(html), tier=2, ok=True, error=None)
