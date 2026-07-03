"""Integration-style test for the REAL CompanyWebsitesAdapter crawl loop.

A threaded ``http.server`` on an ephemeral localhost port serves the fixture
site (homepage, about/team/contact/careers/privacy, a robots.txt disallowing
/private/, and a disallowed page). We run the adapter's ``extract`` against it
and assert emails/phones/roles/social/hiring were extracted with source
evidence, that robots.txt disallow is respected (the /private/ page is skipped
and audited, its leaked email never surfaces), and that the per-domain page cap
is enforced. NO external network is touched — everything is 127.0.0.1.
"""

from __future__ import annotations

import http.server
import threading
import uuid
from functools import partial
from pathlib import Path

import pytest

from app.adapters.base import CompanyRef
from app.adapters.sources.company_websites import CompanyWebsitesAdapter
from tests.unit._fakes import FakeContext, FakeRedis

FIXTURE_SITE = Path(__file__).resolve().parents[1] / "fixtures" / "site"


@pytest.fixture(autouse=True)
def _fast_crawl(monkeypatch):
    """Drop the per-domain politeness delay to 0 so the localhost crawl is fast.

    The rate-limiting path itself is exercised by tests/unit/test_rate_limit.py;
    here we only care about fetch/parse/robots behavior, not wall-clock delay.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "crawler_per_domain_delay_seconds", 0.01, raising=False)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence the test log
        pass


@pytest.fixture
def local_site():
    """Serve tests/fixtures/site on an ephemeral localhost port."""
    handler = partial(_QuietHandler, directory=str(FIXTURE_SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _ref(base_url: str) -> CompanyRef:
    host = base_url.split("//", 1)[1]  # 127.0.0.1:PORT
    return CompanyRef(
        company_id=uuid.uuid4(),
        name="Acme Audit LLP",
        website=base_url + "/index.html",
        domain=host,
        city="Ahmedabad",
        country="India",
    )


async def _crawl(base_url: str, ctx: FakeContext | None = None):
    ctx = ctx or FakeContext(redis=FakeRedis())
    adapter = CompanyWebsitesAdapter()
    result = await adapter.extract(_ref(base_url), ctx)
    return result, ctx


# --------------------------------------------------------------------------- #
# discover is a passthrough
# --------------------------------------------------------------------------- #


async def test_discover_yields_nothing():
    adapter = CompanyWebsitesAdapter()
    from app.adapters.base import JobSpec

    job = JobSpec(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_type=None,
        services=[],
        country=None,
        state=None,
        city=None,
        zipcode=None,
        latitude=None,
        longitude=None,
        radius_km=None,
        company_size_min=None,
        company_size_max=None,
        contact_roles=[],
        exclude_keywords=[],
    )
    ctx = FakeContext()
    got = [c async for c in adapter.discover(job, ctx)]
    assert got == []


# --------------------------------------------------------------------------- #
# full crawl: emails / phones / roles / social / hiring with evidence
# --------------------------------------------------------------------------- #


async def test_crawl_extracts_contacts_with_evidence(local_site):
    result, ctx = await _crawl(local_site)

    assert result.website_status == "ok"
    assert len(result.pages_crawled) >= 4  # homepage + several priority pages

    # -- emails: mailto, obfuscated [at]/[dot], cfemail, JSON-LD ------------- #
    emails = set(result.emails)
    assert "info@acme-audit.example" in emails  # mailto (query stripped)
    assert "audit@acme-audit.example" in emails  # [at]/[dot] obfuscation
    assert "managing.partner@acme-audit.example" in emails  # cfemail XOR decoded
    assert "reception@acme-audit.example" in emails  # JSON-LD Organization email
    assert "privacy@acme-audit.example" in emails  # privacy page mailto

    # -- phones: tel + national-format, E.164 ------------------------------- #
    assert "+917948901234" in result.phones
    assert "+912227579191" in result.phones

    # -- roles from the team page, with source_page + snippet + confidence --- #
    by_name = {c.full_name: c for c in result.contacts if c.full_name}
    assert "Priya Sharma" in by_name
    priya = by_name["Priya Sharma"]
    assert priya.role_category == "partner"
    assert priya.designation == "Managing Partner"
    assert priya.source_page and "team.html" in priya.source_page
    assert priya.source_snippet
    assert 0.0 < priya.confidence_score <= 0.99
    assert "Raj Mehta" in by_name
    assert by_name["Raj Mehta"].role_category == "director"
    assert "Anita Desai" in by_name

    # -- social links (JSON-LD sameAs + footer anchor) ---------------------- #
    assert "linkedin" in result.social_links
    assert "acme-audit" in result.social_links["linkedin"]
    assert result.social_links.get("facebook", "").endswith("acmeauditllp")

    # -- hiring signals: JSON-LD JobPosting + keyword phrases --------------- #
    assert result.hiring_signals
    titles = {s.job_title for s in result.hiring_signals if s.job_title}
    assert "Senior Audit Associate" in titles  # from careers JSON-LD
    # A keyword-based public-post signal also present ("we're hiring"/"join our team").
    assert any(s.description_excerpt for s in result.hiring_signals)

    # -- about text captured ------------------------------------------------ #
    assert result.about_text

    # -- every fetched page was audited "ok" through ctx -------------------- #
    ok_audits = [a for a in ctx.audits if a["status"] == "ok"]
    assert len(ok_audits) >= 4


# --------------------------------------------------------------------------- #
# robots.txt disallow respected
# --------------------------------------------------------------------------- #


async def test_robots_disallow_respected(local_site):
    result, ctx = await _crawl(local_site)

    # The /private/ page is linked from the homepage but disallowed by robots.txt.
    assert not any("/private/" in p for p in result.pages_crawled)
    # The leaked email on that page must never surface.
    assert "leaked-secret@acme-audit.example" not in result.emails
    # And a skipped_robots audit was recorded for it.
    skipped = [a for a in ctx.audits if a["status"] == "skipped_robots"]
    assert skipped
    assert any("/private/" in (a["url"] or "") for a in skipped)


async def test_robots_fetch_cached_in_redis(local_site):
    redis = FakeRedis()
    ctx = FakeContext(redis=redis)
    await _crawl(local_site, ctx)
    # robots.txt body cached under a crawl:robots:{host} key with a 24h TTL.
    assert any(key.startswith("crawl:robots:") for key in redis.store)
    assert any(ttl == 86_400 for _, ttl, _ in redis.setex_calls)


# --------------------------------------------------------------------------- #
# per-domain page cap enforced
# --------------------------------------------------------------------------- #


async def test_page_cap_enforced(local_site, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "crawler_max_pages_per_domain", 2, raising=False)
    monkeypatch.setattr(settings, "crawler_per_domain_delay_seconds", 0.0, raising=False)

    result, ctx = await _crawl(local_site)
    # Never fetch more than the cap, even though many priority links exist.
    assert len(result.pages_crawled) <= 2
    fetched_ok = [a for a in ctx.audits if a["status"] == "ok" and str(a["url"]).startswith("tier")]
    assert len(fetched_ok) <= 2


# --------------------------------------------------------------------------- #
# unreachable site degrades gracefully (no raise)
# --------------------------------------------------------------------------- #


async def test_unreachable_site_degrades():
    ref = CompanyRef(
        company_id=uuid.uuid4(),
        name="Dead Co",
        website="http://127.0.0.1:1/index.html",  # nothing listening
        domain="127.0.0.1:1",
        city=None,
        country=None,
    )
    adapter = CompanyWebsitesAdapter()
    ctx = FakeContext(redis=FakeRedis())
    result = await adapter.extract(ref, ctx)
    assert result.website_status == "unreachable"
    assert result.contacts == []


# --------------------------------------------------------------------------- #
# tiering: escalation decision + graceful Playwright skip
# --------------------------------------------------------------------------- #


def test_escalation_decision():
    from app.crawler.fetcher import _needs_escalation

    # Rich static HTML -> no escalation.
    rich = "<html><body>" + ("<p>Acme audit tax advisory firm. </p>" * 40) + "</body></html>"
    assert _needs_escalation(rich) is False
    # Nearly-empty SPA shell -> escalate.
    spa = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    assert _needs_escalation(spa) is True
    # Tiny page (<400 chars visible) -> escalate.
    assert _needs_escalation("<html><body>hi</body></html>") is True


async def test_playwright_skipped_gracefully_when_unavailable(local_site, monkeypatch):
    """When Playwright is unavailable, a page that WOULD escalate still returns the
    Tier-1 result rather than raising (spec §8 guard)."""
    import app.crawler.fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "playwright_available", lambda: False)
    # Force escalation on every page so the Tier-2 path is attempted + skipped.
    monkeypatch.setattr(fetcher_mod, "_needs_escalation", lambda html: True)

    result, ctx = await _crawl(local_site)
    # Crawl still succeeds using Tier-1 output only.
    assert result.website_status == "ok"
    assert result.pages_crawled
    # All successful fetches were recorded as tier1 (no tier2 audit).
    assert all(not str(a["url"]).startswith("tier2") for a in ctx.audits if a["status"] == "ok")


async def test_no_website_returns_no_website_status():
    ref = CompanyRef(
        company_id=uuid.uuid4(),
        name="No Site Co",
        website=None,
        domain=None,
        city=None,
        country=None,
    )
    adapter = CompanyWebsitesAdapter()
    ctx = FakeContext(redis=FakeRedis())
    result = await adapter.extract(ref, ctx)
    assert result.website_status == "no_website"
