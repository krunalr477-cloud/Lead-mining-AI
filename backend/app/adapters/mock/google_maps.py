"""MockGoogleMapsAdapter (GREEN) — demo Places discovery for Ahmedabad CA firms.

Streams ~250 plausible Ahmedabad chartered-accountancy firms (spec §21) drawn
from the committed seed corpus, in a job-seeded order. Records the same audit +
usage trail a real Places run would produce, so the demo funnel is realistic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.adapters.base import DiscoveredCompany, JobSpec, SourceAdapter
from app.adapters.mock._common import load_corpus, rng_from
from app.constants import AccessMethod, Posture, SourceName

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["MockGoogleMapsAdapter"]

# Demo-funnel tuning (spec §21 target ≈248 companies). We emit a deterministic,
# job-seeded slice of the committed 250-firm corpus so the demo lands near the
# published distribution; directories add the unique directory-only firms on top.
MAPS_DEMO_LIMIT = 188


class MockGoogleMapsAdapter(SourceAdapter):
    name = SourceName.GOOGLE_MAPS
    source_type = "places_api"
    access_method = AccessMethod.MOCK
    posture = Posture.GREEN
    default_enabled = True
    requires_signoff = False
    required_credentials = ["google_maps_api_key"]
    legal_note = "Google Maps Platform Places API. Demo data when no key configured."

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        companies: list[dict] = load_corpus("google_maps_companies.json")  # type: ignore[assignment]
        rng = rng_from(job.job_id, "google_maps")
        order = list(range(len(companies)))
        rng.shuffle(order)
        # Emit a stable slice sized to the demo target (spec §21).
        order = order[:MAPS_DEMO_LIMIT]

        # One "text search" audit entry (the query), then paginated detail hits.
        query = f"{job.company_type or 'CA Firm'} in {job.city or 'Ahmedabad'}"
        ctx.audit(
            f"places:textsearch?query={query}",
            status="ok",
            records_found=len(companies),
        )
        ctx.record_usage("google_maps", "places.textsearch", unit_cost=0.032)

        for _page_start in range(0, len(order), 20):
            ctx.record_usage("google_maps", "places.details", unit_cost=0.017, request_count=20)

        for idx in order:
            row = companies[idx]
            yield DiscoveredCompany(
                name=row["name"],
                source_name=SourceName.GOOGLE_MAPS.value,
                source_url=f"https://maps.google.com/?cid={row['google_place_id']}",
                website=row["website"],
                domain=row["domain"],
                phone=row["phone"],
                address=row["address"],
                city=row["city"],
                state=row["state"],
                country=row["country"],
                postal_code=row["postal_code"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                industry=row["industry"],
                services=list(row["services"]),
                company_size=row["company_size"],
                google_place_id=row["google_place_id"],
                google_rating=row["google_rating"],
                google_reviews=row["google_reviews"],
                raw_payload={"locality": row["locality"], "mock": True},
                is_demo=True,
            )
