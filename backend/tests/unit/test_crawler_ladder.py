"""Batch-7 fetch ladder — retries, SSL fallback, UA policy, variants, blocked.

All network is httpx.MockTransport or monkeypatched PageFetcher.fetch; the only
live resolver touch is *.invalid robots probes (guaranteed NXDOMAIN, fail-open).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

import app.crawler.fetcher as fetcher_mod
from app.adapters.base import CompanyRef
from app.adapters.sources.company_websites import CompanyWebsitesAdapter
from app.config import get_settings
from app.crawler.extract import _homepage_candidates
from app.crawler.fetcher import FetchResult, PageFetcher
from tests.unit._fakes import FakeContext, FakeRedis

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(fetcher_mod, "_RETRY_BACKOFFS", (0.0, 0.0))


def _ref(website: str) -> CompanyRef:
    return CompanyRef(
        company_id=uuid.uuid4(),
        name="Ladder Co",
        website=website,
        domain=None,
        city=None,
        country=None,
    )


# --------------------------------------------------------------------------- #
# Retry ladder (httpx.MockTransport)
# --------------------------------------------------------------------------- #


async def test_transient_dns_error_retries_then_succeeds():
    calls = {"n": 0}

    body = "<html><body>" + "real content " * 60 + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError(
                "[Errno 8] nodename nor servname provided, or not known", request=request
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=body.encode()
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = PageFetcher(client, per_domain_delay=0.0, allow_playwright=False)
    result = await fetcher.fetch("https://flaky.example/")
    await client.aclose()

    assert result.ok
    assert result.tier == 1
    assert calls["n"] == 3  # two transient failures + one success


async def test_403_forever_reports_http_403_kind():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"content-type": "text/html"}, content=b"blocked")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = PageFetcher(client, per_domain_delay=0.0, allow_playwright=False)
    result = await fetcher.fetch("https://waf.example/")
    await client.aclose()

    assert not result.ok
    assert result.error_kind == "http_403"


async def test_non_transient_404_does_not_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, headers={"content-type": "text/html"}, content=b"nope")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = PageFetcher(client, per_domain_delay=0.0, allow_playwright=False)
    result = await fetcher.fetch("https://gone.example/")
    await client.aclose()

    assert not result.ok
    assert result.error_kind == "http_4xx"
    assert calls["n"] == 1  # hard 4xx short-circuits the ladder


async def test_ssl_error_recovers_via_insecure_client():
    def secure_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch",
            request=request,
        )

    body = "<html><body>" + "insecure but alive " * 40 + "</body></html>"

    def insecure_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(secure_handler))
    insecure = httpx.AsyncClient(transport=httpx.MockTransport(insecure_handler))
    fetcher = PageFetcher(
        client, per_domain_delay=0.0, allow_playwright=False, insecure_client=insecure
    )
    result = await fetcher.fetch("https://badcert.example/")
    await client.aclose()
    await insecure.aclose()

    assert result.ok
    assert result.ssl_insecure is True


async def test_browser_ua_sent_and_playwright_budget_respected():
    seen_ua = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua["ua"] = request.headers.get("user-agent", "")
        return httpx.Response(403, headers={"content-type": "text/html"}, content=b"blocked")

    launched = {"n": 0}

    async def _fake_pw(self, url):
        launched["n"] += 1
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = PageFetcher(
        client, per_domain_delay=0.0, allow_playwright=True, may_use_playwright=lambda: False
    )
    # Budget exhausted -> Playwright never attempted even on a clearable 403.
    import unittest.mock as um

    with um.patch.object(PageFetcher, "_fetch_playwright", _fake_pw):
        result = await fetcher.fetch("https://waf.example/")
    await client.aclose()

    assert not result.ok
    assert launched["n"] == 0
    assert seen_ua["ua"] == get_settings().crawler_browser_user_agent
    assert "LeadMineBot" not in seen_ua["ua"]


# --------------------------------------------------------------------------- #
# Homepage candidates + crawl_company status taxonomy
# --------------------------------------------------------------------------- #


async def test_homepage_candidates_variants():
    cands = _homepage_candidates(_ref("https://acme.example/"))
    assert cands[0] == "https://acme.example/"
    assert "http://acme.example/" in cands
    assert "https://www.acme.example/" in cands
    assert len(cands) == 4
    # IP/port hosts get no www toggle.
    ip_cands = _homepage_candidates(_ref("http://127.0.0.1:1/index.html"))
    assert all("www." not in c for c in ip_cands)
    assert len(ip_cands) == 2


async def test_variant_recovery_marks_site_ok(monkeypatch):
    """https fails with DNS; the http:// variant works -> crawl succeeds."""
    body = "<html><body>" + "variant works " * 60 + "</body></html>"

    async def fake_fetch(self, url, *, attempts=None):
        if url.startswith("https://"):
            return FetchResult(
                url, 0, "", 0, tier=0, ok=False,
                error="[Errno 8] nodename nor servname provided", error_kind="dns",
            )
        return FetchResult(url, 200, body, 700, tier=1, ok=True)

    monkeypatch.setattr(PageFetcher, "fetch", fake_fetch)
    ref = _ref("https://variant-co.invalid/")
    result = await CompanyWebsitesAdapter().extract(ref, FakeContext(redis=FakeRedis()))
    assert result.website_status == "ok"
    assert result.pages_crawled  # crawled under the http:// variant
    assert result.pages_crawled[0].startswith("http://")


async def test_blocked_status_when_homepage_403(monkeypatch):
    async def fake_fetch(self, url, *, attempts=None):
        return FetchResult(
            url, 403, "", 0, tier=1, ok=False, error="http_403", error_kind="http_403"
        )

    monkeypatch.setattr(PageFetcher, "fetch", fake_fetch)
    ref = _ref("https://walled-co.invalid/")
    result = await CompanyWebsitesAdapter().extract(ref, FakeContext(redis=FakeRedis()))
    assert result.website_status == "blocked"
    assert result.contacts == []
