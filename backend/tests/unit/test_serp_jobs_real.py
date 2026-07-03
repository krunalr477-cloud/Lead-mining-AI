"""Real SerpJobsAdapter unit tests — respx-mocked, no live network / no DB.

Covers, for BOTH providers (serpapi + serper):
- Google-Jobs payload -> ExtractedHiringSignal(JOB_POSTING) mapping (title,
  company back-match, location, posted_at from a relative string, source URL,
  description excerpt).
- The provider is selected off ``settings.serp_provider`` and the right endpoint
  is hit (the other provider's endpoint is never called).
- One ``serp_jobs / jobs.search`` usage unit is recorded per query; the audit
  trail carries no API key.
- 429 is transient: the adapter returns no signals and records no usage.
- Adjacent-firm postings are dropped so a signal back-matches the queried firm.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters.base import CompanyRef
from app.adapters.sources.serp_jobs import (
    SERPAPI_URL,
    SERPER_URL,
    SerpJobsAdapter,
    _parse_posted_at,
)
from app.config import get_settings
from app.constants import HiringSignalType
from tests.unit._fakes import FakeContext

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SERPAPI_FIXTURE = FIXTURES / "serp_google_jobs_serpapi.json"
SERPER_FIXTURE = FIXTURES / "serp_google_jobs_serper.json"


def _company() -> CompanyRef:
    return CompanyRef(
        company_id=uuid.uuid4(),
        name="Analytical Engines Ltd",
        website="https://analyticalengines.com",
        domain="analyticalengines.com",
        city="Ahmedabad",
        country="India",
    )


@pytest.fixture
def serpapi_payload() -> dict:
    return json.loads(SERPAPI_FIXTURE.read_text())


@pytest.fixture
def serper_payload() -> dict:
    return json.loads(SERPER_FIXTURE.read_text())


@pytest.fixture(autouse=True)
def _serp_key(monkeypatch):
    """Provide a key so the real adapter runs; clear the settings cache after."""
    monkeypatch.setenv("SERP_API_KEY", "test-serp-key-123")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _use_provider(monkeypatch, provider: str) -> None:
    monkeypatch.setenv("SERP_PROVIDER", provider)
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# serpapi provider
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_serpapi_maps_job_postings(monkeypatch, serpapi_payload):
    _use_provider(monkeypatch, "serpapi")
    route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json=serpapi_payload))
    # The serper endpoint must NOT be called for the serpapi provider.
    serper_route = respx.post(SERPER_URL).mock(return_value=httpx.Response(200, json={}))
    ctx = FakeContext()

    result = await SerpJobsAdapter().extract(_company(), ctx)

    assert route.called
    assert not serper_route.called
    signals = result.hiring_signals
    assert len(signals) == 2
    first = signals[0]
    assert first.signal_type is HiringSignalType.JOB_POSTING
    assert first.source == "serp_jobs"
    assert first.job_title == "Senior Audit Associate"
    assert first.location == "Ahmedabad, Gujarat, India"
    assert first.posted_at is not None  # "3 days ago" -> resolved datetime
    assert first.source_url == "https://careers.analyticalengines.com/jobs/senior-audit-associate"
    assert first.description_excerpt and "Senior Audit Associate" in first.description_excerpt

    # engine=google_jobs was requested and the API key never entered the audit trail.
    sent = route.calls.last.request
    assert "engine=google_jobs" in str(sent.url)
    assert "api_key=test-serp-key-123" in str(sent.url)
    assert all("test-serp-key-123" not in (a["url"] or "") for a in ctx.audits)


@pytest.mark.asyncio
@respx.mock
async def test_serpapi_records_one_search_unit(monkeypatch, serpapi_payload):
    _use_provider(monkeypatch, "serpapi")
    respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json=serpapi_payload))
    ctx = FakeContext()

    await SerpJobsAdapter().extract(_company(), ctx)

    searches = [u for u in ctx.usages if u["endpoint"] == "jobs.search"]
    assert len(searches) == 1
    assert searches[0]["provider"] == "serp_jobs"
    assert searches[0]["unit_cost"] == 0.005
    assert any(a["status"] == "ok" for a in ctx.audits)


# --------------------------------------------------------------------------- #
# serper provider
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_serper_maps_job_postings(monkeypatch, serper_payload):
    _use_provider(monkeypatch, "serper")
    route = respx.post(SERPER_URL).mock(return_value=httpx.Response(200, json=serper_payload))
    serpapi_route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json={}))
    ctx = FakeContext()

    result = await SerpJobsAdapter().extract(_company(), ctx)

    assert route.called
    assert not serpapi_route.called
    signals = result.hiring_signals
    assert len(signals) == 2
    first = signals[0]
    assert first.signal_type is HiringSignalType.JOB_POSTING
    assert first.job_title == "Senior Audit Associate"
    assert first.location == "Ahmedabad, Gujarat, India"
    assert first.posted_at is not None
    assert first.source_url == (
        "https://www.linkedin.com/jobs/view/senior-audit-associate-at-analytical-engines"
    )
    assert first.description_excerpt

    # Serper takes the key in the X-API-KEY header, not the URL/audit trail.
    sent = route.calls.last.request
    assert sent.headers["X-API-KEY"] == "test-serp-key-123"
    assert all("test-serp-key-123" not in (a["url"] or "") for a in ctx.audits)


@pytest.mark.asyncio
@respx.mock
async def test_serper_records_one_search_unit(monkeypatch, serper_payload):
    _use_provider(monkeypatch, "serper")
    respx.post(SERPER_URL).mock(return_value=httpx.Response(200, json=serper_payload))
    ctx = FakeContext()

    await SerpJobsAdapter().extract(_company(), ctx)

    searches = [u for u in ctx.usages if u["endpoint"] == "jobs.search"]
    assert len(searches) == 1
    assert searches[0]["provider"] == "serp_jobs"


# --------------------------------------------------------------------------- #
# provider switch, transient errors, back-match
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_provider_switch_hits_only_selected_endpoint(monkeypatch, serper_payload):
    """Flipping settings.serp_provider changes which driver/endpoint runs."""
    _use_provider(monkeypatch, "serper")
    serper_route = respx.post(SERPER_URL).mock(
        return_value=httpx.Response(200, json=serper_payload)
    )
    serpapi_route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json={}))

    await SerpJobsAdapter().extract(_company(), FakeContext())

    assert serper_route.called
    assert not serpapi_route.called


@pytest.mark.asyncio
@respx.mock
async def test_rate_limited_returns_no_signals_no_usage(monkeypatch):
    _use_provider(monkeypatch, "serpapi")
    respx.get(SERPAPI_URL).mock(return_value=httpx.Response(429, json={"error": "throttled"}))
    ctx = FakeContext()

    result = await SerpJobsAdapter().extract(_company(), ctx)

    assert result.hiring_signals == []
    assert not any(u["endpoint"] == "jobs.search" for u in ctx.usages)
    assert any(a["status"] == "error" for a in ctx.audits)


@pytest.mark.asyncio
@respx.mock
async def test_adjacent_firm_postings_dropped(monkeypatch):
    """Postings whose company name doesn't back-match the queried firm are dropped."""
    _use_provider(monkeypatch, "serpapi")
    payload = {
        "jobs_results": [
            {
                "title": "Barista",
                "company_name": "Completely Different Cafe",
                "location": "Ahmedabad",
                "description": "Make coffee.",
                "detected_extensions": {"posted_at": "1 day ago"},
                "apply_options": [{"link": "https://example.com/barista"}],
            },
            {
                "title": "Audit Associate",
                "company_name": "Analytical Engines Ltd",
                "location": "Ahmedabad",
                "description": "Audit work.",
                "detected_extensions": {"posted_at": "2 days ago"},
                "apply_options": [{"link": "https://example.com/audit"}],
            },
        ]
    }
    respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json=payload))

    result = await SerpJobsAdapter().extract(_company(), FakeContext())

    assert len(result.hiring_signals) == 1
    assert result.hiring_signals[0].job_title == "Audit Associate"


@pytest.mark.asyncio
@respx.mock
async def test_no_key_returns_empty_no_network(monkeypatch):
    monkeypatch.setenv("SERP_API_KEY", "")
    get_settings.cache_clear()
    route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json={}))

    result = await SerpJobsAdapter().extract(_company(), FakeContext())

    assert result.hiring_signals == []
    assert not route.called


def test_parse_posted_at_relative_forms():
    from datetime import datetime

    base = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    assert _parse_posted_at("3 days ago", now=base) == datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    assert _parse_posted_at("12 hours ago", now=base) == datetime(2026, 7, 3, 0, 0, tzinfo=UTC)
    assert _parse_posted_at("Just posted", now=base) == base
    assert _parse_posted_at("yesterday", now=base) == datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    assert _parse_posted_at(None, now=base) is None
    assert _parse_posted_at("garbled", now=base) is None
