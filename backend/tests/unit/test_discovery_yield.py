"""Batch-8 discovery yield: query-variant fan-out, geo tiling, rectangle
locationRestriction + haversine filter, and the social-website blocklist.

Offline: Places is respx-intercepted; tiling/haversine are pure math.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import respx

from app.adapters.base import JobSpec
from app.adapters.sources.geo_tiling import haversine_km, tile_circle
from app.adapters.sources.google_maps import (
    PLACES_SEARCH_TEXT_URL,
    GoogleMapsAdapter,
    _is_non_company_website,
)
from app.config import get_settings
from tests.unit._fakes import FakeContext


def _job(**overrides: Any) -> JobSpec:
    base = dict(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_type="CA Firm",
        services=[],
        country="India",
        state="Gujarat",
        city="Ahmedabad",
        zipcode=None,
        latitude=23.0225,
        longitude=72.5714,
        radius_km=25.0,
        company_size_min=None,
        company_size_max=None,
        contact_roles=[],
        exclude_keywords=[],
    )
    base.update(overrides)
    return JobSpec(**base)


def _place(pid: str, lat: float = 23.03, lng: float = 72.58, website: str | None = None) -> dict:
    return {
        "id": pid,
        "displayName": {"text": f"Firm {pid}"},
        "location": {"latitude": lat, "longitude": lng},
        **({"websiteUri": website} if website else {}),
    }


async def _drain(adapter: GoogleMapsAdapter, job: JobSpec, ctx: FakeContext) -> list:
    return [c async for c in adapter.discover(job, ctx)]


# --------------------------------------------------------------------------- #
# Tiling math (pure)
# --------------------------------------------------------------------------- #


def test_tile_circle_seven_disk_cover():
    tiles = tile_circle(23.0, 72.5, 25.0)
    assert len(tiles) == 7
    assert all(abs(r - 12.5) < 1e-9 for _, _, r in tiles)
    # Cover property (sampled): every point of the original circle is inside
    # at least one tile (with a small epsilon for the degree->km approximation).
    import math

    for frac in (0.0, 0.5, 0.9, 1.0):
        for bearing_deg in range(0, 360, 20):
            b = math.radians(bearing_deg)
            d = 25.0 * frac
            plat = 23.0 + (d * math.cos(b)) / 110.574
            plng = 72.5 + (d * math.sin(b)) / (111.320 * math.cos(math.radians(23.0)))
            assert any(
                haversine_km(plat, plng, tlat, tlng) <= tr * 1.05 for tlat, tlng, tr in tiles
            ), f"uncovered point at {frac=} {bearing_deg=}"


def test_tile_circle_degenerate_radius():
    assert tile_circle(23.0, 72.5, 0.5) == [(23.0, 72.5, 0.5)]


def test_haversine_known_distance():
    # Ahmedabad -> Gandhinagar is ~25km.
    d = haversine_km(23.0225, 72.5714, 23.2156, 72.6369)
    assert 20 < d < 30


# --------------------------------------------------------------------------- #
# Website blocklist (pure)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url, blocked",
    [
        ("https://www.linkedin.com/in/someone", True),
        ("https://facebook.com/acmefirm", True),
        ("https://linktr.ee/acme", True),
        ("https://www.justdial.com/Ahmedabad/acme", True),
        ("https://acmefirm.com", False),
        ("http://www.acmefirm.in/about", False),
        (None, False),
    ],
)
def test_is_non_company_website(url, blocked):
    assert _is_non_company_website(url) is blocked


# --------------------------------------------------------------------------- #
# discover(): variants, restriction body, distance filter, blocklist mapping
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_discover_fans_out_variants_and_dedupes(monkeypatch):
    monkeypatch.setattr(get_settings(), "places_query_variants", 3, raising=False)
    bodies: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        bodies.append(payload)
        # Same place in every variant response + one unique per variant.
        return httpx.Response(
            200,
            json={"places": [_place("shared"), _place(f"uniq-{len(bodies)}")]},
        )

    respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=responder)
    out = await _drain(GoogleMapsAdapter(api_key="K"), _job(), FakeContext())

    assert len(bodies) == 3  # one search per variant (no pagination tokens)
    queries = {b["textQuery"] for b in bodies}
    assert len(queries) == 3  # distinct phrasings
    # 'shared' yielded once (cross-variant place-id dedupe) + 3 uniques.
    names = [c.google_place_id for c in out]
    assert names.count("shared") == 1
    assert len(out) == 4
    # locationRestriction rectangle replaces the old soft locationBias.
    for b in bodies:
        assert "locationBias" not in b
        rect = b["locationRestriction"]["rectangle"]
        assert rect["low"]["latitude"] < 23.0225 < rect["high"]["latitude"]


@pytest.mark.asyncio
@respx.mock
async def test_discover_drops_far_away_results(monkeypatch):
    monkeypatch.setattr(get_settings(), "places_query_variants", 1, raising=False)
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    _place("near", lat=23.03, lng=72.58),
                    _place("far", lat=19.0760, lng=72.8777),  # Mumbai, ~440km away
                    {"id": "no-coords", "displayName": {"text": "No Coords"}},
                ]
            },
        )
    )
    out = await _drain(GoogleMapsAdapter(api_key="K"), _job(), FakeContext())
    ids = [c.google_place_id for c in out]
    assert "near" in ids
    assert "far" not in ids  # beyond radius*1.2 -> dropped
    assert "no-coords" in ids  # coordinate-less results pass through


@pytest.mark.asyncio
@respx.mock
async def test_discover_deep_discovery_tiles(monkeypatch):
    monkeypatch.setattr(get_settings(), "places_query_variants", 2, raising=False)
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"places": []})

    respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=responder)
    await _drain(GoogleMapsAdapter(api_key="K"), _job(deep_discovery=True), FakeContext())
    assert calls["n"] == 7 * 2  # 7 tiles x 2 variants


@pytest.mark.asyncio
@respx.mock
async def test_discover_search_cap_bounds_spend(monkeypatch):
    monkeypatch.setattr(get_settings(), "places_query_variants", 3, raising=False)
    monkeypatch.setattr(get_settings(), "places_max_searches_per_job", 5, raising=False)
    calls = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"places": []})

    respx.post(PLACES_SEARCH_TEXT_URL).mock(side_effect=responder)
    await _drain(GoogleMapsAdapter(api_key="K"), _job(deep_discovery=True), FakeContext())
    assert calls["n"] == 5  # capped, not 21


@pytest.mark.asyncio
@respx.mock
async def test_map_place_blocks_social_website(monkeypatch):
    monkeypatch.setattr(get_settings(), "places_query_variants", 1, raising=False)
    respx.post(PLACES_SEARCH_TEXT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    _place("li", website="https://www.linkedin.com/in/ca-someone"),
                    _place("fb", website="https://facebook.com/firmpage"),
                    _place("real", website="https://realfirm.in"),
                ]
            },
        )
    )
    out = {c.google_place_id: c for c in await _drain(
        GoogleMapsAdapter(api_key="K"), _job(), FakeContext()
    )}
    assert out["li"].website is None and out["li"].domain is None
    assert out["li"].raw_payload["listed_website"].startswith("https://www.linkedin.com")
    assert out["fb"].website is None
    assert out["fb"].facebook_page_url == "https://facebook.com/firmpage"
    assert out["real"].website == "https://realfirm.in"
    assert out["real"].domain == "realfirm.in"
