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
from app.adapters.sources.firm_taxonomy import expand_company_type
from app.constants import AccessMethod, Posture, SourceName

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


def _text_query(job: JobSpec) -> str:
    """Build the free-text query from company type + services + city.

    The company type is expanded through the firm taxonomy so industry shorthand
    (CPA, KPO, BPO, IT, MSP, ...) becomes a phrase Places can actually match,
    while unknown types pass through so any firm is still targetable.
    """
    parts: list[str] = []
    expanded = expand_company_type(job.company_type)
    if expanded:
        parts.append(expanded)
    if job.services:
        parts.append(" ".join(job.services[:3]))
    where = job.city or job.state or job.country
    if where:
        parts.append(f"in {where}")
    return " ".join(p for p in parts if p).strip() or "companies"


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
            website=website,
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
            raw_payload={"places_new": True, "place_id": place_id},
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

    def _location_bias(self, job: JobSpec, center: tuple[float, float] | None) -> dict | None:
        if center is None:
            return None
        radius_m = float(job.radius_km) * 1000.0 if job.radius_km else 5000.0
        # Places (New) circle radius must be within (0, 50000] metres.
        radius_m = max(1.0, min(radius_m, 50000.0))
        return {
            "circle": {
                "center": {"latitude": center[0], "longitude": center[1]},
                "radius": radius_m,
            }
        }

    # -- discover ----------------------------------------------------------- #

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        """Text Search over ``places:searchText`` with a location-biased circle.

        Geocodes the job location first when lat/lng is missing, then paginates
        via ``nextPageToken`` up to MAX_PAGES. Deduplicates by place id within
        the run. Every network touch is audited + metered by construction.
        """
        seen: set[str] = set()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            center = await self._resolve_center(client, job, ctx)
            bias = self._location_bias(job, center)

            payload: dict[str, Any] = {"textQuery": _text_query(job)}
            if bias is not None:
                payload["locationBias"] = bias

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
                    yield self._map_place(place)

                page_token = body.get("nextPageToken")
                if not page_token:
                    break
