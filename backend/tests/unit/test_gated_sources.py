"""Unit tests for the REAL gated provider-backed source adapters (spec §8).

Sources under test (all disabled-by-default, sign-off-gated):
- Yellow Pages / Clutch (AMBER) — licensed-provider directory discovery.
- Indeed (AMBER) — approved-provider HIRING SIGNALS.
- LinkedIn (RED) — official-connector STUB, ALWAYS unavailable.

Fully offline: httpx is intercepted by respx; no fixture ever points at a real
host. Two states are proven for each provider-backed source:

1. NO provider configured -> ``SourceUnavailableError`` (the worker records a
   skipped SourceRun and the mining job CONTINUES). No network is touched.
2. A FAKE provider configured (respx-mocked base_url) -> Yellow Pages / Clutch
   return ``DiscoveredCompany`` records; Indeed returns ``ExtractedHiringSignal``.

LinkedIn is ALWAYS unavailable with the scraping-not-supported message, in every
state.

Compliance assertion (belt-and-suspenders): after every scenario we assert NO
request ever hit ``linkedin.com`` / ``facebook.com`` or any first-party
scrape/login/auth URL — only the admin-configured fake provider host.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx

from app.adapters.base import DiscoveredCompany, ExtractedHiringSignal, JobSpec
from app.adapters.sources._provider_base import ProviderConfig, SourceUnavailableError
from app.adapters.sources.clutch import ClutchAdapter
from app.adapters.sources.indeed import IndeedAdapter
from app.adapters.sources.linkedin import LINKEDIN_UNAVAILABLE_REASON, LinkedInAdapter
from app.adapters.sources.yellow_pages import YellowPagesAdapter
from app.constants import HiringSignalType, Posture

# The admin-configured approved provider (fake, respx-mocked). NEVER a first-party
# directory host — the adapters ship NO scraping.
FAKE_PROVIDER_BASE = "https://api.approved-provider.test/v1"

# Hosts an adapter must NEVER touch: first-party directory sites, LinkedIn /
# Facebook, and any login/auth surface.
FORBIDDEN_HOST_FRAGMENTS = (
    "linkedin.com",
    "facebook.com",
    "yellowpages.com",
    "clutch.co",
    "indeed.com",
    "/login",
    "/auth",
    "signin",
)


@dataclass
class FakeCtx:
    """Records audit + usage; no DB. session/tenant_id None => no provider row.

    The provider-base resolves config from ``session``/``tenant_id``; leaving them
    None makes ``_provider_config`` return None (the unconfigured case). Configured
    tests override ``adapter._provider_config`` directly instead of standing up a DB.
    """

    session: Any = None
    tenant_id: Any = None
    audits: list[dict[str, Any]] = field(default_factory=list)
    usages: list[dict[str, Any]] = field(default_factory=list)

    def audit(self, url, status, *, records_found=0, error=None):
        self.audits.append(
            {"url": url, "status": status, "records_found": records_found, "error": error}
        )

    def record_usage(self, provider, endpoint, unit_cost, request_count=1):
        self.usages.append({"provider": provider, "endpoint": endpoint, "unit_cost": unit_cost})


def _job(**overrides: Any) -> JobSpec:
    base = dict(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_type="Chartered Accountants",
        services=["audit", "tax"],
        country="India",
        state="Gujarat",
        city="Ahmedabad",
        zipcode=None,
        latitude=None,
        longitude=None,
        radius_km=10.0,
        company_size_min=None,
        company_size_max=None,
        contact_roles=[],
        exclude_keywords=[],
    )
    base.update(overrides)
    return JobSpec(**base)


def _configure(adapter, monkeypatch, base_url: str = FAKE_PROVIDER_BASE) -> None:
    """Point a provider-backed adapter at the fake approved provider."""
    monkeypatch.setattr(
        adapter,
        "_provider_config",
        lambda ctx: ProviderConfig(base_url=base_url, api_key="fake-provider-key"),
    )


def _assert_no_forbidden_hosts(mock_router: respx.Router) -> None:
    """No request in the run touched a forbidden (scrape/login/social) URL."""
    for call in mock_router.calls:
        url = str(call.request.url)
        for fragment in FORBIDDEN_HOST_FRAGMENTS:
            assert fragment not in url, f"forbidden URL touched: {url}"


async def _drain(adapter, job, ctx) -> list:
    return [c async for c in adapter.discover(job, ctx)]


# --------------------------------------------------------------------------- #
# 1. No provider configured -> SourceUnavailable (job continues)
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_cls", [YellowPagesAdapter, ClutchAdapter, IndeedAdapter])
async def test_no_provider_configured_is_unavailable(adapter_cls):
    adapter = adapter_cls()
    ctx = FakeCtx()  # session/tenant None -> no provider row -> unavailable

    with pytest.raises(SourceUnavailableError) as excinfo:
        await _drain(adapter, _job(), ctx)

    assert excinfo.value.detail.source_name == adapter.name.value
    assert "no licensed provider configured" in excinfo.value.detail.reason
    # Nothing was fetched: no audit, no usage, no network.
    assert ctx.audits == []
    assert ctx.usages == []
    assert respx.calls.call_count == 0
    _assert_no_forbidden_hosts(respx.mock)


@respx.mock
@pytest.mark.asyncio
async def test_indeed_search_signals_unavailable_without_provider():
    adapter = IndeedAdapter()
    ctx = FakeCtx()
    with pytest.raises(SourceUnavailableError):
        await adapter.search_signals(_job(), ctx)
    assert respx.calls.call_count == 0


# --------------------------------------------------------------------------- #
# 2a. Yellow Pages / Clutch with a fake provider -> DiscoveredCompany
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_cls,search_path",
    [(YellowPagesAdapter, "/companies/search"), (ClutchAdapter, "/providers/search")],
)
async def test_directory_provider_returns_companies(adapter_cls, search_path, monkeypatch):
    payload = {
        "results": [
            {
                "name": "Sharma & Associates",
                "website": "https://www.sharmaca.co.in",
                "phone": "+91 79 4000 1234",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "country": "India",
                "postal_code": "380015",
                "industry": "Accounting",
                "source_url": "https://api.approved-provider.test/listing/1",
            },
            {"company_name": "Mehta & Patel LLP", "url": "http://mehtapatel.in"},
            {"no_name": "skipped — must be dropped"},
        ]
    }
    route = respx.get(f"{FAKE_PROVIDER_BASE}{search_path}").mock(
        return_value=httpx.Response(200, json=payload)
    )

    adapter = adapter_cls()
    _configure(adapter, monkeypatch)
    ctx = FakeCtx()
    companies = await _drain(adapter, _job(), ctx)

    assert route.called
    # Bearer auth header carried the key (never the audit URL).
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer fake-provider-key"

    # Two mappable rows; the nameless row was dropped.
    assert len(companies) == 2
    first = companies[0]
    assert isinstance(first, DiscoveredCompany)
    assert first.name == "Sharma & Associates"
    assert first.source_name == adapter.name.value
    assert first.website == "https://www.sharmaca.co.in"
    assert first.domain == "sharmaca.co.in"
    assert first.phone == "+91 79 4000 1234"
    assert first.city == "Ahmedabad"
    assert first.postal_code == "380015"
    assert first.is_demo is False
    assert first.raw_payload["licensed"] is True

    second = companies[1]
    assert second.name == "Mehta & Patel LLP"
    assert second.domain == "mehtapatel.in"

    # Audited + metered exactly once (the provider search), key-free audit URL.
    ok_audits = [a for a in ctx.audits if a["status"] == "ok"]
    assert len(ok_audits) == 1
    assert "fake-provider-key" not in ok_audits[0]["url"]
    assert len(ctx.usages) == 1
    assert ctx.usages[0]["provider"] == adapter.name.value

    _assert_no_forbidden_hosts(respx.mock)


@respx.mock
@pytest.mark.asyncio
async def test_directory_provider_transient_failure_yields_nothing(monkeypatch):
    # A 429 from the provider must NOT crash the job — the source yields nothing.
    respx.get(f"{FAKE_PROVIDER_BASE}/companies/search").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    adapter = YellowPagesAdapter()
    _configure(adapter, monkeypatch)
    companies = await _drain(adapter, _job(), FakeCtx())
    assert companies == []


# --------------------------------------------------------------------------- #
# 2b. Indeed with a fake provider -> HiringSignals
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
async def test_indeed_provider_returns_hiring_signals(monkeypatch):
    payload = {
        "results": [
            {
                "job_title": "Audit Associate",
                "location": "Ahmedabad",
                "url": "https://api.approved-provider.test/jobs/1",
                "description": "Hiring qualified CA for audit engagements.",
            },
            {"title": "Tax Manager", "city": "Ahmedabad"},
            {"no_title": "dropped"},
        ]
    }
    route = respx.get(f"{FAKE_PROVIDER_BASE}/jobs/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    adapter = IndeedAdapter()
    _configure(adapter, monkeypatch)
    ctx = FakeCtx()

    # discover() introduces NO companies for a hiring-signal source.
    companies = await _drain(adapter, _job(), ctx)
    assert companies == []

    signals = await adapter.search_signals(_job(), ctx)
    assert route.called
    assert len(signals) == 2
    first = signals[0]
    assert isinstance(first, ExtractedHiringSignal)
    assert first.source == "indeed"
    assert first.signal_type == HiringSignalType.JOB_POSTING
    assert first.job_title == "Audit Associate"
    assert first.location == "Ahmedabad"
    assert first.source_url == "https://api.approved-provider.test/jobs/1"
    assert signals[1].job_title == "Tax Manager"

    _assert_no_forbidden_hosts(respx.mock)


# --------------------------------------------------------------------------- #
# 3. LinkedIn — ALWAYS unavailable, scraping not supported, never any request
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
async def test_linkedin_discover_always_unavailable():
    adapter = LinkedInAdapter()
    ctx = FakeCtx()

    with pytest.raises(SourceUnavailableError) as excinfo:
        await _drain(adapter, _job(), ctx)

    detail = excinfo.value.detail
    assert detail.source_name == "linkedin"
    assert detail.posture == Posture.RED
    assert detail.reason == LINKEDIN_UNAVAILABLE_REASON
    assert "scraping is not supported" in detail.reason
    # No network whatsoever — the stub raises before any access.
    assert respx.calls.call_count == 0
    assert ctx.audits == []
    _assert_no_forbidden_hosts(respx.mock)


@respx.mock
@pytest.mark.asyncio
async def test_linkedin_extract_never_scrapes():
    from app.adapters.base import CompanyRef

    adapter = LinkedInAdapter()
    ctx = FakeCtx()
    ref = CompanyRef(
        company_id=uuid.uuid4(),
        name="Sharma & Associates",
        website="https://sharmaca.co.in",
        domain="sharmaca.co.in",
        city="Ahmedabad",
        country="India",
    )
    result = await adapter.extract(ref, ctx)
    assert result.contacts == []
    assert result.hiring_signals == []
    # extract() touched no network at all.
    assert respx.calls.call_count == 0
    _assert_no_forbidden_hosts(respx.mock)


def test_linkedin_module_ships_no_http_client_or_scrape_url():
    """Static proof: the LinkedIn adapter imports no HTTP client and hard-codes no
    scheme-qualified linkedin.com URL — it cannot scrape by construction.

    (The module's docstring names ``linkedin.com`` / ``httpx`` in prose to state
    what it must NOT do; we scan the AST's imports + string constants, not prose.)
    """
    import ast
    import inspect

    import app.adapters.sources.linkedin as mod

    tree = ast.parse(inspect.getsource(mod))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # No HTTP client is imported anywhere in the module.
    assert "httpx" not in imported
    assert "requests" not in imported
    assert "urllib" not in imported

    # No string constant is a scheme-qualified LinkedIn/Facebook URL.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if lowered.startswith(("http://", "https://")):
                assert "linkedin.com" not in lowered
                assert "facebook.com" not in lowered
