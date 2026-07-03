"""Unit tests for the REAL GoogleMapsAdapter (Places API New + Geocoding).

Fully offline: httpx is intercepted by respx and all responses come from JSON
fixtures under tests/fixtures/. NO real network is touched. We assert the
DiscoveredCompany mapping, domain extraction, address parsing, rating/reviews,
nextPageToken pagination, the strict + minimal X-Goog-FieldMask header, and that
every call is audited + metered through the SourceRunContext helpers.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters.base import JobSpec
from app.adapters.google.geocode import GEOCODE_URL
from app.adapters.sources.google_maps import (
    PLACES_FIELD_MASK,
    PLACES_SEARCH_TEXT_URL,
    GoogleMapsAdapter,
    SourcePermanentError,
    SourceTransientError,
    _domain_from_url,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


@dataclass
class FakeCtx:
    """Records audit + usage instead of writing to a DB — the adapter only ever
    touches the network through these two helpers."""

    audits: list[dict[str, Any]] = field(default_factory=list)
    usages: list[dict[str, Any]] = field(default_factory=list)

    def audit(self, url, status, *, records_found=0, error=None):
        self.audits.append(
            {"url": url, "status": status, "records_found": records_found, "error": error}
        )

    def record_usage(self, provider, endpoint, unit_cost, request_count=1):
        self.usages.append(
            {
                "provider": provider,
                "endpoint": endpoint,
                "unit_cost": unit_cost,
                "request_count": request_count,
            }
        )


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


async def _drain(adapter: GoogleMapsAdapter, job: JobSpec, ctx: FakeCtx) -> list:
    return [c async for c in adapter.discover(job, ctx)]


# --------------------------------------------------------------------------- #
# domain extraction (pure)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.sharmaca.co.in/services", "sharmaca.co.in"),
        ("http://mehtapatel.in", "mehtapatel.in"),
        ("https://WWW.Example.COM/path?x=1", "example.com"),
        ("example.org", "example.org"),
        (None, None),
        ("", None),
    ],
)
def test_domain_extraction(url, expected):
    assert _domain_from_url(url) == expected


# --------------------------------------------------------------------------- #
# happy path: geocode -> searchText page 1 (nextPageToken) -> page 2
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
async def test_discover_paginates_and_maps(monkeypatch):
    page1 = _load("places_searchtext.json")
    page2 = _load("places_searchtext_page2.json")
    geo = _load("geocode_ahmedabad.json")

    geo_route = respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geo))

    calls: list[dict] = []

    def _search_responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        # First call has no pageToken; second carries the nextPageToken.
        if body.get("pageToken") == "PAGE2TOKEN":
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    search_route = respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=_search_responder)

    adapter = GoogleMapsAdapter(api_key="TEST_KEY")
    ctx = FakeCtx()
    companies = await _drain(adapter, _job(), ctx)

    # geocode ran (no lat/lng on the job) then two search pages.
    assert geo_route.called
    assert search_route.call_count == 2
    assert calls[0].get("pageToken") is None
    assert calls[1]["pageToken"] == "PAGE2TOKEN"

    # 2 places on page1 + 1 on page2.
    assert len(companies) == 3

    first = companies[0]
    assert first.google_place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert first.name == "Sharma & Associates Chartered Accountants"
    assert first.website == "https://www.sharmaca.co.in/services"
    assert first.domain == "sharmaca.co.in"
    assert first.phone == "+91 79 4000 1234"
    assert first.city == "Ahmedabad"
    assert first.state == "Gujarat"
    assert first.country == "India"
    assert first.postal_code == "380015"
    assert first.google_rating == 4.6
    assert first.google_reviews == 128
    assert first.latitude == 23.0245
    assert first.longitude == 72.5079
    assert first.source_name == "google_maps"

    # A place with NO websiteUri yields domain None (page2 entry).
    no_site = companies[2]
    assert no_site.website is None
    assert no_site.domain is None
    assert no_site.google_reviews == 8


# --------------------------------------------------------------------------- #
# field mask header is set and minimal
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
async def test_field_mask_header_is_strict_and_minimal():
    captured: dict[str, str] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"places": []})

    respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=_responder)

    # lat/lng present -> no geocode call needed.
    adapter = GoogleMapsAdapter(api_key="K")
    ctx = FakeCtx()
    await _drain(adapter, _job(latitude=23.0, longitude=72.5), ctx)

    mask = captured["x-goog-fieldmask"]
    assert mask == PLACES_FIELD_MASK
    fields = set(mask.split(","))
    # Only the cheap fields we map + pagination token.
    assert fields == {
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.location",
        "places.addressComponents",
        "nextPageToken",
    }
    # No expensive Atmosphere/Enterprise fields leaked in.
    for banned in ("reviews", "photos", "openingHours", "editorialSummary", "priceLevel"):
        assert banned not in mask
    assert captured["x-goog-api-key"] == "K"


# --------------------------------------------------------------------------- #
# audit + usage recorded
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
async def test_audit_and_usage_recorded():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(200, json=_load("places_searchtext_page2.json"))
    )

    adapter = GoogleMapsAdapter(api_key="K")
    ctx = FakeCtx()
    await _drain(adapter, _job(latitude=23.0, longitude=72.5), ctx)

    # One search page -> one ok audit + one metered usage.
    ok_audits = [a for a in ctx.audits if a["status"] == "ok"]
    assert len(ok_audits) == 1
    assert ok_audits[0]["records_found"] == 1
    assert ok_audits[0]["url"] == PLACES_SEARCH_TEXT_URL

    place_usage = [u for u in ctx.usages if u["endpoint"] == "places.searchText"]
    assert len(place_usage) == 1
    assert place_usage[0]["provider"] == "google_places"
    assert place_usage[0]["unit_cost"] > 0


# --------------------------------------------------------------------------- #
# error classification: 429 transient, 400 permanent
# --------------------------------------------------------------------------- #


@respx.mock
@pytest.mark.asyncio
async def test_429_is_transient():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(return_value=httpx.Response(429, text="slow down"))
    adapter = GoogleMapsAdapter(api_key="K")
    ctx = FakeCtx()
    with pytest.raises(SourceTransientError):
        await _drain(adapter, _job(latitude=23.0, longitude=72.5), ctx)


@respx.mock
@pytest.mark.asyncio
async def test_400_is_permanent():
    respx.post(PLACES_SEARCH_TEXT_URL).mock(return_value=httpx.Response(400, text="bad field mask"))
    adapter = GoogleMapsAdapter(api_key="K")
    ctx = FakeCtx()
    with pytest.raises(SourcePermanentError):
        await _drain(adapter, _job(latitude=23.0, longitude=72.5), ctx)


def test_adapter_requires_key():
    with pytest.raises(ValueError):
        GoogleMapsAdapter(api_key="")
