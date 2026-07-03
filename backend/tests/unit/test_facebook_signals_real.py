"""Real FacebookSignalsAdapter unit tests — respx-mocked, NO network, NO DB.

Compliance-critical (spec §8 "Facebook Pages and Hiring Signals"). We assert:

- Mode 2 (public page discovery via SERP): a ``site:facebook.com`` web search maps
  to a ``DiscoveredCompany`` carrying ONLY the public page URL / name / category
  (facebook_page_url), and NO personal-profile data. Personal profiles, groups,
  Messenger, etc. in the SERP payload are dropped.
- The adapter REFUSES / returns the unavailable path CLEANLY when no compliant
  access exists (no SERP key AND no authorized Page credential): discover() yields
  nothing (audited skip, job continues) and check_access() explains why.
- NO request is EVER made to a Facebook login or profile endpoint. Only the public
  SERP web-search endpoint and — in authorized-page mode — the Graph *page-node*
  endpoint are ever hit. respx is configured to raise if any login/profile/graph
  /me/groups/messenger URL is touched.
- Mode 1 (authorized Graph Page) reads only the low-sensitivity PUBLIC page fields
  and surfaces a hiring signal from a permitted public field; the token never
  enters the audit trail.
- Mode 3 (hiring fallback) maps SERP Google-Jobs postings to hiring signals.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters.base import CompanyRef, JobSpec
from app.adapters.sources.facebook_signals import (
    GRAPH_API_BASE,
    SERPAPI_SEARCH_URL,
    FacebookSignalsAdapter,
    facebook_page_from_url,
)
from app.config import get_settings
from app.constants import HiringSignalType
from tests.unit._fakes import FakeContext, FakeRedis

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FB_PAGES_FIXTURE = FIXTURES / "serp_facebook_pages.json"
FB_JOBS_FIXTURE = FIXTURES / "serp_google_jobs_serpapi.json"


# --------------------------------------------------------------------------- #
# fakes / helpers
# --------------------------------------------------------------------------- #


class FakeScalarSession:
    """Minimal session: returns a pre-seeded credential for scalar()."""

    def __init__(self, credential: Any | None) -> None:
        self._credential = credential

    def scalar(self, _stmt: Any) -> Any | None:
        return self._credential


class DBFakeContext(FakeContext):
    """FakeContext + the session/tenant surface the mode-1 credential lookup uses."""

    def __init__(self, credential: Any | None = None) -> None:
        super().__init__(redis=FakeRedis())
        self.session = FakeScalarSession(credential)
        self.tenant_id = uuid.uuid4()


class FakeCredential:
    """Stand-in for IntegrationCredential(provider='facebook')."""

    def __init__(self, secret: str, scopes: list[str] | None = None) -> None:
        self.encrypted_secret_reference = secret
        self.scopes = scopes or []
        self.status = "active"


def _job(**overrides: Any) -> JobSpec:
    base = dict(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_type="Sharma & Associates Chartered Accountants",
        services=["audit", "tax"],
        country="India",
        state="Gujarat",
        city="Ahmedabad",
        zipcode=None,
        latitude=None,
        longitude=None,
        radius_km=None,
        company_size_min=None,
        company_size_max=None,
        contact_roles=[],
        exclude_keywords=[],
    )
    base.update(overrides)
    return JobSpec(**base)


def _company() -> CompanyRef:
    return CompanyRef(
        company_id=uuid.uuid4(),
        name="Sharma & Associates Chartered Accountants",
        website="https://sharmaca.co.in",
        domain="sharmaca.co.in",
        city="Ahmedabad",
        country="India",
    )


async def _drain(adapter: FacebookSignalsAdapter, job: JobSpec, ctx: Any) -> list:
    return [c async for c in adapter.discover(job, ctx)]


@pytest.fixture
def with_serp_key(monkeypatch):
    monkeypatch.setenv("SERP_API_KEY", "test-serp-key-xyz")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def no_serp_key(monkeypatch):
    monkeypatch.setenv("SERP_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _forbid_login_and_profile_routes() -> None:
    """Register respx routes that BLOW UP if a login/profile endpoint is touched.

    Any request to a login page, a user/profile/group/messenger node, or the Graph
    ``/me`` self node fails the test loudly (compliance guard, spec §8).
    """
    for pattern in (
        "https://www.facebook.com/login",
        "https://m.facebook.com/login",
        "https://www.facebook.com/profile.php",
        "https://graph.facebook.com/v19.0/me",
        "https://www.facebook.com/groups/",
        "https://www.facebook.com/messages/",
    ):
        respx.route(url__startswith=pattern).mock(
            side_effect=AssertionError(f"forbidden endpoint touched: {pattern}")
        )


# --------------------------------------------------------------------------- #
# pure URL filter (never captures a personal profile / group / messenger)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://www.facebook.com/SharmaAssociatesCA",
            "https://www.facebook.com/SharmaAssociatesCA",
        ),
        ("facebook.com/AcmeLtd", "https://www.facebook.com/AcmeLtd"),
        ("https://m.facebook.com/Sharma/jobs", "https://www.facebook.com/Sharma"),
        # personal profiles / groups / messenger / events -> rejected
        ("https://www.facebook.com/profile.php?id=100001", None),
        ("https://www.facebook.com/people/Ramesh/1234", None),
        ("https://www.facebook.com/groups/ahmedabadca", None),
        ("https://www.facebook.com/messages/t/123", None),
        ("https://www.facebook.com/events/999", None),
        ("https://www.facebook.com/story.php?id=1", None),
        # non-facebook host -> rejected
        ("https://www.linkedin.com/company/acme", None),
        (None, None),
        ("", None),
    ],
)
def test_facebook_page_from_url_rejects_non_pages(url, expected):
    assert facebook_page_from_url(url) == expected


# --------------------------------------------------------------------------- #
# mode 2: public page discovery via SERP
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_mode2_discovers_public_page_url_only(with_serp_key):
    payload = json.loads(FB_PAGES_FIXTURE.read_text())
    route = respx.get(SERPAPI_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
    _forbid_login_and_profile_routes()

    ctx = FakeContext()
    companies = await _drain(FacebookSignalsAdapter(), _job(), ctx)

    assert route.called
    # Two PAGE results (SharmaAssociatesCA page + its /jobs page, deduped to one
    # slug) — the group, the personal profile, and the LinkedIn link are dropped.
    urls = {c.facebook_page_url for c in companies}
    assert urls == {"https://www.facebook.com/SharmaAssociatesCA"}

    company = companies[0]
    assert company.source_name == "facebook_signals"
    assert company.facebook_page_url == "https://www.facebook.com/SharmaAssociatesCA"
    assert company.source_url == "https://www.facebook.com/SharmaAssociatesCA"
    assert company.name == "Sharma & Associates Chartered Accountants"
    assert company.industry == "Accountant"  # category from rich_snippet, NOT profile data

    # Only URL / name / category are captured — no personal-profile fields exist on
    # the record, and the raw payload is limited to public page metadata.
    assert company.raw_payload["facebook_mode"] == "public_page_signal"
    assert set(company.raw_payload) == {
        "facebook_mode",
        "page_url",
        "page_name",
        "page_category",
    }
    assert company.phone is None
    assert company.description is None

    # engine=google web search was used with a site:facebook.com query; the API key
    # never entered the audit trail.
    sent = route.calls.last.request
    assert "engine=google" in str(sent.url)
    assert "site%3Afacebook.com" in str(sent.url) or "site:facebook.com" in str(sent.url)
    assert all("test-serp-key-xyz" not in (a["url"] or "") for a in ctx.audits)

    # A discovery usage unit was metered.
    disc = [u for u in ctx.usages if u["endpoint"] == "facebook.page.discovery"]
    assert len(disc) == 1
    assert disc[0]["provider"] == "serpapi"


@pytest.mark.asyncio
@respx.mock
async def test_mode2_never_requests_login_or_profile(with_serp_key):
    """The adapter hits the SERP endpoint ONLY — never facebook.com login/profile."""
    payload = json.loads(FB_PAGES_FIXTURE.read_text())
    serp_route = respx.get(SERPAPI_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
    _forbid_login_and_profile_routes()

    await _drain(FacebookSignalsAdapter(), _job(), FakeContext())

    # Exactly one outbound request, and it was the SERP search.
    assert serp_route.called
    assert len(respx.calls) == 1
    assert str(respx.calls.last.request.url).startswith(SERPAPI_SEARCH_URL)


# --------------------------------------------------------------------------- #
# graceful refusal when no compliant access exists
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_no_access_discover_yields_nothing_no_network(no_serp_key):
    """No SERP key + no Page credential -> discover yields nothing, touches no network."""
    route = respx.get(SERPAPI_SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    _forbid_login_and_profile_routes()

    ctx = FakeContext()  # no session -> no Page credential
    companies = await _drain(FacebookSignalsAdapter(), _job(), ctx)

    assert companies == []
    assert not route.called
    assert len(respx.calls) == 0
    # A clear skip was audited so the job's SourceRun explains the refusal.
    skips = [a for a in ctx.audits if a["status"] == "skipped"]
    assert skips and "no approved SERP" in (skips[0]["error"] or "")


@pytest.mark.asyncio
@respx.mock
async def test_no_access_extract_returns_empty_no_network(no_serp_key):
    route = respx.get(SERPAPI_SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    _forbid_login_and_profile_routes()

    ctx = FakeContext()
    result = await FacebookSignalsAdapter().extract(_company(), ctx)

    assert result.hiring_signals == []
    assert not route.called
    assert len(respx.calls) == 0
    assert any(a["status"] == "skipped" for a in ctx.audits)


def test_check_access_reports_unavailable_reason(no_serp_key):
    """check_access() returns a SourceUnavailable with a human reason (refusal path)."""
    ctx = FakeContext()  # no session, no serp key
    unavailable = FacebookSignalsAdapter().check_access(ctx)
    assert unavailable is not None
    assert unavailable.source_name == "facebook_signals"
    assert unavailable.posture.value == "amber"
    assert "no compliant Facebook access" in unavailable.reason


def test_check_access_ok_with_serp_key(with_serp_key):
    ctx = FakeContext()
    assert FacebookSignalsAdapter().check_access(ctx) is None


# --------------------------------------------------------------------------- #
# mode 1: authorized Graph Page read (page-node only, never /me or a profile)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_mode1_authorized_page_reads_public_fields_only(no_serp_key):
    """A stored Page credential -> Graph page-node read of PUBLIC fields -> signal.

    No SERP key here, so mode 3 does nothing; the ONLY network call is the Graph
    page-node GET. The token is passed as a query param but MUST NOT appear in the
    audit trail.
    """
    from app.security.crypto import get_cipher

    page_id = "1234567890"
    token = "EAAG-super-secret-page-token"
    secret = get_cipher().encrypt(f"{page_id}:{token}")
    cred = FakeCredential(secret)

    page_fields = {
        "id": page_id,
        "name": "Sharma & Associates Chartered Accountants",
        "link": "https://www.facebook.com/SharmaAssociatesCA",
        "category": "Accountant",
        "website": "https://sharmaca.co.in",
        "single_line_address": "Ahmedabad, India",
        "about": "Audit and tax firm. We're hiring audit associates now.",
    }
    graph_route = respx.get(f"{GRAPH_API_BASE}/{page_id}").mock(
        return_value=httpx.Response(200, json=page_fields)
    )
    _forbid_login_and_profile_routes()

    ctx = DBFakeContext(credential=cred)
    result = await FacebookSignalsAdapter().extract(_company(), ctx)

    assert graph_route.called
    # Only the page node was hit — never /me, never a profile node.
    assert len(respx.calls) == 1
    assert str(respx.calls.last.request.url).startswith(f"{GRAPH_API_BASE}/{page_id}")

    # A hiring signal was surfaced from the permitted PUBLIC field.
    signals = result.hiring_signals
    assert len(signals) == 1
    assert signals[0].signal_type is HiringSignalType.PUBLIC_POST
    assert signals[0].source == "facebook_page"
    assert signals[0].source_url == "https://www.facebook.com/SharmaAssociatesCA"

    # The strict, low-sensitivity field mask was requested (no posts/insights/fans).
    sent_url = str(graph_route.calls.last.request.url)
    assert "fields=" in sent_url
    for banned in ("insights", "posts", "fan_count", "followers"):
        assert banned not in sent_url

    # The secret token NEVER entered the audit trail.
    assert all(token not in (a["url"] or "") for a in ctx.audits)
    graph_usage = [u for u in ctx.usages if u["endpoint"] == "graph.page"]
    assert len(graph_usage) == 1
    assert graph_usage[0]["provider"] == "facebook"


# --------------------------------------------------------------------------- #
# mode 3: hiring fallback via SERP Google Jobs
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_mode3_hiring_fallback_maps_jobs(with_serp_key):
    """With a SERP key and no Page credential, extract() yields SERP-jobs signals."""
    jobs_payload = json.loads(FB_JOBS_FIXTURE.read_text())

    def _responder(request: httpx.Request) -> httpx.Response:
        # google_jobs -> the jobs fixture; the careers web search -> empty.
        if "engine=google_jobs" in str(request.url):
            return httpx.Response(200, json=jobs_payload)
        return httpx.Response(200, json={"organic_results": []})

    respx.get(SERPAPI_SEARCH_URL).mock(side_effect=_responder)
    _forbid_login_and_profile_routes()

    ref = CompanyRef(
        company_id=uuid.uuid4(),
        name="Analytical Engines Ltd",
        website="https://analyticalengines.com",
        domain="analyticalengines.com",
        city="Ahmedabad",
        country="India",
    )
    ctx = FakeContext()
    result = await FacebookSignalsAdapter().extract(ref, ctx)

    job_signals = [
        s for s in result.hiring_signals if s.signal_type is HiringSignalType.JOB_POSTING
    ]
    assert len(job_signals) == 2
    assert job_signals[0].job_title == "Senior Audit Associate"
    assert job_signals[0].source == "serp_jobs"
    assert job_signals[0].posted_at is not None
    # The API key never leaked into the audit trail.
    assert all("test-serp-key-xyz" not in (a["url"] or "") for a in ctx.audits)


@pytest.mark.asyncio
@respx.mock
async def test_mode3_careers_page_signal(with_serp_key):
    """A careers page found on the company's own domain -> a CAREERS_PAGE signal."""
    careers_payload = {
        "organic_results": [
            {
                "title": "Careers - Sharma & Associates",
                "link": "https://sharmaca.co.in/careers",
                "snippet": "We're hiring! Open positions for audit associates.",
            }
        ]
    }

    def _responder(request: httpx.Request) -> httpx.Response:
        if "engine=google_jobs" in str(request.url):
            return httpx.Response(200, json={"jobs_results": []})
        return httpx.Response(200, json=careers_payload)

    respx.get(SERPAPI_SEARCH_URL).mock(side_effect=_responder)
    _forbid_login_and_profile_routes()

    result = await FacebookSignalsAdapter().extract(_company(), FakeContext())
    careers = [s for s in result.hiring_signals if s.signal_type is HiringSignalType.CAREERS_PAGE]
    assert len(careers) == 1
    assert careers[0].source_url == "https://sharmaca.co.in/careers"


# --------------------------------------------------------------------------- #
# transient SERP failure is graceful
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_serp_rate_limited_discover_yields_nothing(with_serp_key):
    respx.get(SERPAPI_SEARCH_URL).mock(return_value=httpx.Response(429, json={"error": "slow"}))
    _forbid_login_and_profile_routes()

    ctx = FakeContext()
    companies = await _drain(FacebookSignalsAdapter(), _job(), ctx)

    assert companies == []
    # No discovery usage was metered for the failed call.
    assert not any(u["endpoint"] == "facebook.page.discovery" for u in ctx.usages)
    assert any(a["status"] == "error" for a in ctx.audits)
