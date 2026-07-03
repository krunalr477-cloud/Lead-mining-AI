"""Geocoding helper — Google Geocoding API (spec §8 "Support ... geocoding").

Resolves a free-text address or city into (latitude, longitude) plus the
resolved administrative components, so Places (New) searches can be biased to a
real circle centre when the job spec has no explicit lat/lng.

Network is touched ONLY through the SourceRunContext, so every geocode call
lands in Data_Source_Audit and APIUsage. Callers pass a shared httpx.AsyncClient
so connection reuse and timeouts are owned by the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["GeocodeResult", "geocode"]

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Geocoding is billed per request (Google list price ≈ $0.005/call).
GEOCODE_UNIT_COST = 0.005

# addressComponent types (Geocoding uses the classic REST shape).
_COMPONENT_TYPES = {
    "locality": "city",
    "postal_town": "city",
    "administrative_area_level_1": "state",
    "country": "country",
    "postal_code": "postal_code",
}


@dataclass(slots=True)
class GeocodeResult:
    latitude: float
    longitude: float
    formatted_address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None
    place_id: str | None = None


def _parse_components(components: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten Geocoding address_components into our normalized keys."""
    out: dict[str, str] = {}
    for comp in components:
        for gtype in comp.get("types", []):
            key = _COMPONENT_TYPES.get(gtype)
            if key and key not in out:
                out[key] = comp.get("long_name") or comp.get("short_name") or ""
    return out


async def geocode(
    client: httpx.AsyncClient,
    api_key: str,
    address: str,
    ctx: SourceRunContext,
) -> GeocodeResult | None:
    """Geocode ``address`` to a GeocodeResult, or None when Google finds nothing.

    Audits the call and records one metered Geocoding usage unit. Raises
    httpx.HTTPStatusError for transient 429/5xx so the adapter can classify
    them; ZERO_RESULTS returns None (a permanent, non-retryable miss).
    """
    params = {"address": address, "key": api_key}
    try:
        response = await client.get(GEOCODE_URL, params=params)
    except httpx.HTTPError as exc:
        ctx.audit(GEOCODE_URL, status="error", error=str(exc))
        raise

    ctx.record_usage("google_geocoding", "geocode", unit_cost=GEOCODE_UNIT_COST)

    if response.status_code >= 400:
        ctx.audit(
            GEOCODE_URL,
            status=f"http_{response.status_code}",
            error=response.text[:500],
        )
        response.raise_for_status()

    body = response.json()
    status = body.get("status", "UNKNOWN")
    results = body.get("results") or []

    if status == "ZERO_RESULTS" or not results:
        ctx.audit(GEOCODE_URL, status="zero_results", records_found=0)
        return None

    if status != "OK":
        # OVER_QUERY_LIMIT etc. — surface as an audited error so the caller
        # decides retry vs. skip. OVER_QUERY_LIMIT is transient by convention.
        ctx.audit(GEOCODE_URL, status=f"api_{status.lower()}", error=body.get("error_message"))
        if status == "OVER_QUERY_LIMIT":
            raise httpx.HTTPStatusError(
                "geocoding over query limit",
                request=response.request,
                response=httpx.Response(429, request=response.request),
            )
        return None

    top = results[0]
    loc = top.get("geometry", {}).get("location", {})
    parts = _parse_components(top.get("address_components", []))
    ctx.audit(GEOCODE_URL, status="ok", records_found=1)
    return GeocodeResult(
        latitude=float(loc["lat"]),
        longitude=float(loc["lng"]),
        formatted_address=top.get("formatted_address"),
        city=parts.get("city"),
        state=parts.get("state"),
        country=parts.get("country"),
        postal_code=parts.get("postal_code"),
        place_id=top.get("place_id"),
    )
