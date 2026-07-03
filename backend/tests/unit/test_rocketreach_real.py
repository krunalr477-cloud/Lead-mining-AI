"""Real RocketReachAdapter unit tests — respx-mocked, no live network / no DB.

Covers: person/lookup payload -> ExtractedContact mapping, one credit recorded,
the 90-day cache preventing a second network call, 429 transient handling, and a
404 (no match) caching an empty result while still charging the credit.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters.enrichment.rocketreach import _LOOKUP_URL, RocketReachAdapter
from app.config import get_settings
from tests.unit._fakes import FakeContext, FakeRedis

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rocketreach_person_lookup.json"


@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(autouse=True)
def _rocketreach_key(monkeypatch):
    """Provide a key so the real adapter runs; clear the settings cache after."""
    monkeypatch.setenv("ROCKETREACH_API_KEY", "test-key-123")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_maps_to_contact(payload):
    route = respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(200, json=payload))
    ctx = FakeContext()
    adapter = RocketReachAdapter()

    contacts = await adapter.enrich(
        company_name="Analytical Engines Ltd",
        domain="analyticalengines.com",
        website="https://analyticalengines.com",
        person_name="Ada Lovelace",
        designation="CTO",
        location="London",
        ctx=ctx,
    )

    assert route.called
    assert len(contacts) == 1
    c = contacts[0]
    assert c.email == "ada.lovelace@analyticalengines.com"  # valid pro email preferred
    assert c.phone == "+1-415-555-0100"
    assert c.linkedin_url == "https://www.linkedin.com/in/ada-lovelace"
    assert c.facebook_url == "https://www.facebook.com/ada.lovelace"
    assert c.designation == "Chief Technology Officer"
    assert c.confidence_score == 0.9  # 'valid' graded work email
    assert c.is_demo is False
    assert c.source_type == "enrichment"

    # Header + params were shaped correctly.
    sent = route.calls.last.request
    assert sent.headers["Api-Key"] == "test-key-123"
    assert "name=Ada+Lovelace" in str(sent.url) or "Ada%20Lovelace" in str(sent.url)


@pytest.mark.asyncio
@respx.mock
async def test_records_one_credit(payload):
    respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(200, json=payload))
    ctx = FakeContext()
    await RocketReachAdapter().enrich(
        company_name="Analytical Engines Ltd",
        domain="analyticalengines.com",
        website=None,
        person_name="Ada Lovelace",
        designation=None,
        location=None,
        ctx=ctx,
    )
    lookups = [u for u in ctx.usages if u["endpoint"] == "person.lookup"]
    assert len(lookups) == 1
    assert lookups[0]["provider"] == "rocketreach"
    assert lookups[0]["unit_cost"] == 0.10
    # And an ok audit event was written (no key in the trail).
    ok = [a for a in ctx.audits if a["status"] == "ok"]
    assert ok and "test-key-123" not in (ok[0]["url"] or "")


@pytest.mark.asyncio
@respx.mock
async def test_cache_prevents_second_call(payload):
    route = respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(200, json=payload))
    redis = FakeRedis()
    adapter = RocketReachAdapter()

    kwargs = dict(
        company_name="Analytical Engines Ltd",
        domain="analyticalengines.com",
        website=None,
        person_name="Ada Lovelace",
        designation=None,
        location=None,
    )
    ctx1 = FakeContext(redis=redis)
    first = await adapter.enrich(ctx=ctx1, **kwargs)
    ctx2 = FakeContext(redis=redis)
    second = await adapter.enrich(ctx=ctx2, **kwargs)

    assert route.call_count == 1  # second lookup served from cache
    assert first[0].email == second[0].email
    # No credit spent on the cached call.
    assert not any(u["endpoint"] == "person.lookup" for u in ctx2.usages)


@pytest.mark.asyncio
@respx.mock
async def test_rate_limited_returns_empty_no_credit():
    respx.get(_LOOKUP_URL).mock(return_value=httpx.Response(429, json={"detail": "throttled"}))
    ctx = FakeContext()
    out = await RocketReachAdapter().enrich(
        company_name="Analytical Engines Ltd",
        domain="analyticalengines.com",
        website=None,
        person_name="Ada Lovelace",
        designation=None,
        location=None,
        ctx=ctx,
    )
    assert out == []
    assert not any(u["endpoint"] == "person.lookup" for u in ctx.usages)
    assert any(a["status"] == "error" for a in ctx.audits)


@pytest.mark.asyncio
@respx.mock
async def test_not_found_charges_and_caches_empty():
    route = respx.get(_LOOKUP_URL).mock(
        return_value=httpx.Response(404, json={"detail": "no match"})
    )
    redis = FakeRedis()
    kwargs = dict(
        company_name="Nowhere Inc",
        domain="nowhere.example",
        website=None,
        person_name="Nobody Here",
        designation=None,
        location=None,
    )
    ctx1 = FakeContext(redis=redis)
    assert await RocketReachAdapter().enrich(ctx=ctx1, **kwargs) == []
    # Credit charged for the (billable) 404 lookup, empty result cached.
    assert any(u["endpoint"] == "person.lookup" for u in ctx1.usages)
    ctx2 = FakeContext(redis=redis)
    assert await RocketReachAdapter().enrich(ctx=ctx2, **kwargs) == []
    assert route.call_count == 1  # second served from the negative cache
