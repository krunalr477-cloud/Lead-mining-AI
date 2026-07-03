"""MockDirectoriesAdapter (GREEN) — public-directory discovery for dedupe exercise.

Yields a mix of companies that OVERLAP the Google Maps corpus (~40% of the maps
set, to drive company deduplication by domain/name/phone) plus a set of unique
directory-only firms. Overlapping rows carry a directory source_url and slightly
different formatting so the dedupe stage has real work to do.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.adapters.base import DiscoveredCompany, JobSpec, SourceAdapter
from app.adapters.mock._common import load_corpus, rng_from
from app.constants import AccessMethod, Posture, SourceName

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["MockDirectoriesAdapter"]

_DIRECTORY_SITES = ["justdial-clone", "sulekha-clone", "indiamart-clone", "grotal-clone"]


class MockDirectoriesAdapter(SourceAdapter):
    name = SourceName.DIRECTORIES
    source_type = "provider_api"
    access_method = AccessMethod.MOCK
    posture = Posture.GREEN
    default_enabled = True
    requires_signoff = False
    required_credentials = []  # open/licensed datasets — no per-tenant key
    legal_note = "Open/licensed public business directories. Demo data in mock mode."

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        maps_companies: list[dict] = load_corpus("google_maps_companies.json")  # type: ignore[assignment]
        directory_only: list[dict] = load_corpus("directory_only_companies.json")  # type: ignore[assignment]
        rng = rng_from(job.job_id, "directories")

        # Overlap must reference only the maps companies that were actually
        # discovered (the maps adapter emits a job-seeded slice sized to the demo
        # target), so an overlap sighting merges into an existing Company instead
        # of minting a phantom new one. Reproduce that slice here.
        from app.adapters.mock.google_maps import MAPS_DEMO_LIMIT

        maps_rng = rng_from(job.job_id, "google_maps")
        emitted_idx = list(range(len(maps_companies)))
        maps_rng.shuffle(emitted_idx)
        emitted_idx = emitted_idx[:MAPS_DEMO_LIMIT]

        # ~40% of the discovered maps set reappears here (dedupe overlap).
        n_overlap = round(0.40 * len(emitted_idx))
        overlap_idx = rng.sample(emitted_idx, n_overlap)

        total = n_overlap + len(directory_only)
        ctx.audit(
            "directories:search?category=chartered-accountants", status="ok", records_found=total
        )
        ctx.record_usage("directories", "directory.search", unit_cost=0.0)

        emitted: list[DiscoveredCompany] = []

        for i in overlap_idx:
            row = maps_companies[i]
            site = rng.choice(_DIRECTORY_SITES)
            # Reformat the name a little so dedupe must normalize, not string-match.
            listed_name = (
                row["name"].replace("& Co.", "and Co").replace("& Associates", "and Associates")
            )
            emitted.append(
                DiscoveredCompany(
                    name=listed_name,
                    source_name=SourceName.DIRECTORIES.value,
                    source_url=f"https://{site}.example/ca/ahmedabad/{i}",
                    website=row["website"],
                    domain=row["domain"],
                    phone=row["phone"],
                    city=row["city"],
                    state=row["state"],
                    country=row["country"],
                    postal_code=row["postal_code"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    industry=row["industry"],
                    services=list(row["services"][:2]),
                    raw_payload={"directory": site, "overlaps_maps": True, "mock": True},
                    is_demo=True,
                )
            )

        for row in directory_only:
            site = rng.choice(_DIRECTORY_SITES)
            emitted.append(
                DiscoveredCompany(
                    name=row["name"],
                    source_name=SourceName.DIRECTORIES.value,
                    source_url=row.get("source_url")
                    or f"https://{site}.example/ca/ahmedabad/u{row['idx']}",
                    website=row["website"],
                    domain=row["domain"],
                    phone=row["phone"],
                    city=row["city"],
                    state=row["state"],
                    country=row["country"],
                    postal_code=row["postal_code"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    industry=row["industry"],
                    services=list(row["services"]),
                    raw_payload={"directory": site, "overlaps_maps": False, "mock": True},
                    is_demo=True,
                )
            )

        rng.shuffle(emitted)
        for company in emitted:
            yield company
