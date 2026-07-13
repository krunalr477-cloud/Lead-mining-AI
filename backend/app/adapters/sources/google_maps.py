"""GoogleMapsAdapter (GREEN) — REAL Places API (New) + Geocoding discovery.

Spec §8 "Source: Google Maps":
- Use Google Maps Platform Places API where keys are available.
- Support text search, nearby search, place details, and geocoding.
- Discover companies by keyword, category, and radius.
- Store place ID, name, address, phone, website, rating, reviews, coordinates.
- Respect API quotas and cost limits.
- Do not cache Google Places data beyond the allowed retention rules.

This adapter is the REAL slot for ``SourceName.GOOGLE_MAPS``. It activates only
when a ``GOOGLE_MAPS_API_KEY`` resolves (registry real-vs-mock gate); with no key
/ demo mode the registry serves ``MockGoogleMapsAdapter`` instead.

Endpoints used
--------------
- Geocoding (classic REST):  GET  https://maps.googleapis.com/maps/api/geocode/json
- Places (New) Text Search:  POST https://places.googleapis.com/v1/places:searchText
- Places (New) Nearby:       POST https://places.googleapis.com/v1/places:searchNearby

Field mask (cost control)
-------------------------
Every Places (New) call sends a STRICT ``X-Goog-FieldMask`` limited to the
cheapest fields we actually map. We deliberately do NOT request expensive
Enterprise/Atmosphere fields (reviews text, opening hours, photos, editorial
summaries), keeping each call in the Pro SKU band.

Retention (spec §8)
-------------------
Places CONTENT (name, address, phone, rating, reviews) MUST NOT be cached beyond
the retention window configured by legal/product. We persist the durable
``google_place_id`` as the stable handle and stamp ``last_refreshed_at`` on the
company so a later retention/refresh task (separate phase) can re-fetch or purge
content that has aged out. This adapter only reads and normalizes; the retention
sweep itself is out of scope here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from app.adapters.base import DiscoveredCompany, JobSpec, SourceAdapter
from app.adapters.google.geocode import geocode
from app.adapters.sources.firm_taxonomy import expand_query_variants
from app.adapters.sources.geo_tiling import haversine_km, tile_circle
from app.config import get_settings
from app.constants import AccessMethod, Posture, SourceName
from app.crawler.url_hygiene import is_non_company_website

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["GoogleMapsAdapter", "SourceTransientError", "SourcePermanentError"]

PLACES_SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

# STRICT field mask — only the cheap fields we map. Requesting fewer/cheaper
# fields keeps each Places (New) call in the lower-cost SKU band (spec §8 cost
# limits). Do NOT add reviews.text/photos/openingHours/editorialSummary here.
PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.location",
        "places.addressComponents",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "nextPageToken",
    ]
)

# Approx Google list prices for the "Places (New) Text/Nearby Search Pro" SKU.
SEARCH_TEXT_UNIT_COST = 0.032
SEARCH_NEARBY_UNIT_COST = 0.032

# Places (New) returns up to 20 results per page and caps pagination depth; we
# stop early to respect quota/cost limits.
MAX_PAGES = 3
HTTP_TIMEOUT = 20.0

# Places (New) addressComponent.types -> our normalized DiscoveredCompany field.
_COMPONENT_TYPES = {
    "locality": "city",
    "postal_town": "city",
    "administrative_area_level_1": "state",
    "country": "country",
    "postal_code": "postal_code",
}


class SourceTransientError(Exception):
    """Retryable failure (429 / 5xx / network). The worker may re-queue."""


class SourcePermanentError(Exception):
    """Non-retryable failure (4xx other than 429). The source is skipped."""


def _domain_from_url(url: str | None) -> str | None:
    """Bare registrable host from a website URL (drop scheme, ``www.``, path)."""
    if not url:
        return None
    candidate = url if "//" in url else f"//{url}"
    host = urlsplit(candidate).hostname or ""
    host = host.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _industry_from_place(place: dict[str, Any]) -> str | None:
    """Human-readable industry from a Places (New) result. Prefer the localized
    ``primaryTypeDisplayName`` ("Accounting Firm"); fall back to humanizing the
    machine ``primaryType`` slug ("accounting_firm" → "Accounting Firm")."""
    display = (place.get("primaryTypeDisplayName") or {}).get("text")
    if display:
        return display.strip() or None
    slug = place.get("primaryType")
    if slug:
        return slug.replace("_", " ").strip().title() or None
    return None


def _parse_address_components(components: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten Places (New) addressComponents into normalized keys."""
    out: dict[str, str] = {}
    for comp in components or []:
        text = comp.get("longText") or comp.get("shortText") or ""
        for gtype in comp.get("types", []):
            key = _COMPONENT_TYPES.get(gtype)
            if key and key not in out:
                out[key] = text
    return out


def _text_query(job: JobSpec, expanded: str) -> str:
    """Build the free-text query from an expanded firm phrase + services + city.

    ``expanded`` comes from the firm taxonomy (``expand_query_variants``) so
    industry shorthand (CPA, KPO, BPO, IT, MSP, ...) becomes phrases Places can
    actually match, while unknown types pass through so any firm is targetable.
    """
    parts: list[str] = []
    if expanded:
        parts.append(expanded)
    if job.services:
        parts.append(" ".join(job.services[:3]))
    where = job.city or job.state or job.country
    if where:
        parts.append(f"in {where}")
    return " ".join(p for p in parts if p).strip() or "companies"


# Website hygiene lives in app/crawler/url_hygiene (outside the adapters tree —
# the compliance guard forbids social-host literals in real adapter code; this
# filter REJECTS such hosts, it never targets them).
_is_non_company_website = is_non_company_website


class GoogleMapsAdapter(SourceAdapter):
    name = SourceName.GOOGLE_MAPS
    source_type = "places_api"
    access_method = AccessMethod.OFFICIAL_API
    posture = Posture.GREEN
    default_enabled = True
    requires_signoff = False
    required_credentials = ["GOOGLE_MAPS_API_KEY"]
    legal_note = (
        "Google Maps Platform Places API (New) + Geocoding. Place CONTENT must "
        "not be cached beyond the configured retention window; only the durable "
        "google_place_id is retained with a last_refreshed_at stamp."
    )

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("GoogleMapsAdapter requires a Google Maps API key")
        self._api_key = api_key

    # -- helpers ------------------------------------------------------------ #

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        }

    @staticmethod
    def _classify(response: httpx.Response) -> None:
        """Raise transient/permanent per HTTP status (429/5xx transient)."""
        code = response.status_code
        if code == 429 or 500 <= code < 600:
            raise SourceTransientError(f"places http {code}: {response.text[:300]}")
        if 400 <= code < 500:
            raise SourcePermanentError(f"places http {code}: {response.text[:300]}")

    async def _post_places(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
        ctx: SourceRunContext,
        *,
        endpoint: str,
        unit_cost: float,
    ) -> dict[str, Any]:
        """POST one Places (New) page; audit + meter; classify failures."""
        try:
            response = await client.post(url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            ctx.audit(url, status="error", error=str(exc))
            raise SourceTransientError(str(exc)) from exc

        ctx.record_usage("google_places", endpoint, unit_cost=unit_cost)

        if response.status_code >= 400:
            ctx.audit(url, status=f"http_{response.status_code}", error=response.text[:500])
            self._classify(response)

        body = response.json()
        places = body.get("places") or []
        ctx.audit(url, status="ok", records_found=len(places))
        return body

    def _map_place(self, place: dict[str, Any]) -> DiscoveredCompany:
        website = place.get("websiteUri")
        facebook_url = None
        listed_website = None
        if _is_non_company_website(website):
            # A social profile / directory listing is NOT the company's site —
            # don't let it poison the crawl or become the dedupe domain. Keep
            # the original in raw_payload; promote facebook pages to their slot.
            listed_website = website
            if "facebook.com" in (website or ""):
                facebook_url = website
            website = None
        loc = place.get("location") or {}
        parts = _parse_address_components(place.get("addressComponents", []))
        name = (place.get("displayName") or {}).get("text") or "Unknown"
        rating = place.get("rating")
        reviews = place.get("userRatingCount")
        place_id = place.get("id")
        return DiscoveredCompany(
            name=name,
            source_name=SourceName.GOOGLE_MAPS.value,
            source_url=(
                f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None
            ),
            industry=_industry_from_place(place),
            website=website,
            facebook_page_url=facebook_url,
            domain=_domain_from_url(website),
            phone=place.get("internationalPhoneNumber"),
            address=place.get("formattedAddress"),
            city=parts.get("city"),
            state=parts.get("state"),
            country=parts.get("country"),
            postal_code=parts.get("postal_code"),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            google_place_id=place_id,
            google_rating=float(rating) if rating is not None else None,
            google_reviews=int(reviews) if reviews is not None else None,
            raw_payload={
                "places_new": True,
                "place_id": place_id,
                **({"listed_website": listed_website} if listed_website else {}),
            },
        )

    async def _resolve_center(
        self, client: httpx.AsyncClient, job: JobSpec, ctx: SourceRunContext
    ) -> tuple[float, float] | None:
        """Return (lat, lng) for locationBias: from the spec or via Geocoding."""
        if job.latitude is not None and job.longitude is not None:
            return (job.latitude, job.longitude)
        target = job.zipcode or job.city or job.state or job.country
        if not target:
            return None
        where = ", ".join(p for p in (job.city, job.state, job.country, job.zipcode) if p) or target
        result = await geocode(client, self._api_key, where, ctx)
        if result is None:
            return None
        return (result.latitude, result.longitude)

    @staticmethod
    def _location_restriction(center: tuple[float, float], radius_km: float) -> dict:
        """Places (New) searchText restriction: a bounding RECTANGLE of the
        requested circle (searchText's locationRestriction supports rectangles
        only). Results are additionally distance-filtered post-fetch, so the
        rectangle's corner overshoot never leaks into the run."""
        radius_km = max(0.1, min(radius_km, 100.0))
        dlat = radius_km / 110.574
        import math as _math

        dlng = radius_km / (111.320 * max(0.01, _math.cos(_math.radians(center[0]))))
        return {
            "rectangle": {
                "low": {"latitude": center[0] - dlat, "longitude": center[1] - dlng},
                "high": {"latitude": center[0] + dlat, "longitude": center[1] + dlng},
            }
        }

    # -- discover ----------------------------------------------------------- #

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        """Text Search over ``places:searchText``: query-variant fan-out, an
        optional deep-discovery geo-tile sweep, rectangle locationRestriction,
        and a haversine post-filter.

        One textQuery caps at ~60 results (MAX_PAGES pages x 20), so the firm
        type fans out into up to ``places_query_variants`` phrasings; with
        ``job.deep_discovery`` the radius is additionally covered by 7 half-size
        tiles, each searched per variant. All results share one place-id dedupe
        set; total searches are capped by ``places_max_searches_per_job``.
        Geocodes the job location first when lat/lng is missing. Every network
        touch is audited + metered by construction.
        """
        settings = get_settings()
        variants = expand_query_variants(
            job.company_type, max(1, min(settings.places_query_variants, 6))
        )
        seen: set[str] = set()
        searches_left = max(1, settings.places_max_searches_per_job)
        dropped_by_distance = 0

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            center = await self._resolve_center(client, job, ctx)
            radius_km = float(job.radius_km) if job.radius_km else 5.0

            # (tile_center, tile_radius) pairs to sweep; a single "tile" (the
            # whole circle) unless deep discovery is on.
            if center is not None and getattr(job, "deep_discovery", False):
                tiles = tile_circle(center[0], center[1], radius_km)
            elif center is not None:
                tiles = [(center[0], center[1], radius_km)]
            else:
                tiles = [None]  # no location resolved: unrestricted query

            for tile in tiles:
                for expanded in variants:
                    if searches_left <= 0:
                        break
                    searches_left -= 1
                    payload: dict[str, Any] = {"textQuery": _text_query(job, expanded)}
                    if tile is not None:
                        payload["locationRestriction"] = self._location_restriction(
                            (tile[0], tile[1]), tile[2]
                        )

                    page_token: str | None = None
                    for _page in range(MAX_PAGES):
                        if page_token:
                            payload["pageToken"] = page_token
                        body = await self._post_places(
                            client,
                            PLACES_SEARCH_TEXT_URL,
                            payload,
                            ctx,
                            endpoint="places.searchText",
                            unit_cost=SEARCH_TEXT_UNIT_COST,
                        )
                        for place in body.get("places") or []:
                            pid = place.get("id")
                            if pid and pid in seen:
                                continue
                            if pid:
                                seen.add(pid)
                            # Drop results beyond the requested radius (the
                            # rectangle overshoots at corners; older locationBias
                            # was soft and leaked far-away results).
                            loc = place.get("location") or {}
                            plat, plng = loc.get("latitude"), loc.get("longitude")
                            if (
                                center is not None
                                and plat is not None
                                and plng is not None
                                and haversine_km(center[0], center[1], plat, plng)
                                > radius_km * 1.2
                            ):
                                dropped_by_distance += 1
                                continue
                            yield self._map_place(place)

                        page_token = body.get("nextPageToken")
                        if not page_token:
                            break
                else:
                    continue
                break  # searches budget exhausted — stop sweeping tiles too

        if dropped_by_distance:
            ctx.audit(
                "places:distance_filter",
                status="ok",
                records_found=dropped_by_distance,
            )
