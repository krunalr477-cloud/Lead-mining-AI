"""Mock adapters for the compliance-gated sources (AMBER/RED, spec §8).

Yellow Pages, Clutch (AMBER) and Indeed, LinkedIn (RED) each stream a small demo
set from the committed gated_sources corpus. These adapters are only *reached* by
the registry when the source is enabled + signed off + the matching global env
flag is on; otherwise the registry short-circuits with SourceUnavailable and the
job logs a skipped SourceRun (graceful degradation, spec §8).

Facebook signals (AMBER) and Google/SERP jobs (GREEN-ish provider) are modeled as
hiring-signal sources: their discover yields no NEW companies but their extract
attaches a hiring signal to a company already in the pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import TYPE_CHECKING

from app.adapters.base import (
    CompanyRef,
    DiscoveredCompany,
    ExtractedHiringSignal,
    ExtractionResult,
    JobSpec,
    SourceAdapter,
)
from app.adapters.mock._common import load_corpus, rng_from, stable_unit
from app.constants import AccessMethod, HiringSignalType, Posture, SourceName
from app.db import utcnow

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = [
    "MockClutchAdapter",
    "MockFacebookSignalsAdapter",
    "MockIndeedAdapter",
    "MockLinkedInAdapter",
    "MockSerpJobsAdapter",
    "MockYellowPagesAdapter",
]


class _GatedListingAdapter(SourceAdapter):
    """Common discover() for the corpus-backed gated directory sources."""

    corpus_key: str
    source_type = "provider_api"
    access_method = AccessMethod.MOCK

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        gated: dict = load_corpus("gated_sources.json")  # type: ignore[assignment]
        rows: list[dict] = gated[self.corpus_key]
        rng = rng_from(job.job_id, self.corpus_key)
        ctx.audit(
            f"{self.corpus_key}:search?category=chartered-accountants",
            status="ok",
            records_found=len(rows),
        )
        ctx.record_usage(self.corpus_key, "listing.search", unit_cost=0.0)
        order = list(range(len(rows)))
        rng.shuffle(order)
        for idx in order:
            row = rows[idx]
            yield DiscoveredCompany(
                name=row["name"],
                source_name=self.name.value,
                source_url=row.get("source_url"),
                website=row.get("website"),
                domain=row.get("domain"),
                city=row.get("city"),
                state=row.get("state"),
                country=row.get("country"),
                postal_code=row.get("postal_code"),
                industry=row.get("industry"),
                raw_payload={"gated_source": self.corpus_key, "mock": True},
                is_demo=True,
            )


class MockYellowPagesAdapter(_GatedListingAdapter):
    name = SourceName.YELLOW_PAGES
    corpus_key = "yellow_pages"
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    required_credentials = []
    legal_note = "Public directory. AMBER: enable + sign off before use."


class MockClutchAdapter(_GatedListingAdapter):
    name = SourceName.CLUTCH
    corpus_key = "clutch"
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    required_credentials = []
    legal_note = "B2B directory. AMBER: enable + sign off before use."


class MockIndeedAdapter(_GatedListingAdapter):
    name = SourceName.INDEED
    corpus_key = "indeed"
    posture = Posture.RED
    default_enabled = False
    requires_signoff = True
    required_credentials = ["serp_api_key"]
    legal_note = "Indeed via approved provider only. RED: gated, off by default."


class MockLinkedInAdapter(_GatedListingAdapter):
    name = SourceName.LINKEDIN
    corpus_key = "linkedin"
    posture = Posture.RED
    default_enabled = False
    requires_signoff = True
    required_credentials = []
    legal_note = (
        "LinkedIn only via official/authorized access. RED: disabled by default; "
        "NO private/authenticated scraping."
    )


class MockFacebookSignalsAdapter(SourceAdapter):
    """AMBER hiring-signal source: attaches public-post signals to known companies."""

    name = SourceName.FACEBOOK_SIGNALS
    source_type = "graph_api"
    access_method = AccessMethod.MOCK
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    required_credentials = []
    legal_note = "Public Facebook Pages/hiring posts only. AMBER: enable + sign off."

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        return
        yield  # pragma: no cover

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        if stable_unit(company.company_id, "fb") >= 0.4:
            return ExtractionResult.empty()
        ctx.audit(f"graph:page_search?q={company.name}", status="ok", records_found=1)
        signal = ExtractedHiringSignal(
            source="facebook",
            signal_type=HiringSignalType.PUBLIC_POST,
            source_url=f"https://facebook.com/{(company.domain or 'firm').split('.')[0]}",
            job_title="We're hiring",
            location=company.city or "Ahmedabad",
            posted_at=utcnow() - timedelta(days=int(10 * stable_unit(company.company_id, "fbd"))),
            description_excerpt="Public Facebook post indicating active hiring.",
            confidence_score=0.55,
        )
        return ExtractionResult(hiring_signals=[signal])


class MockSerpJobsAdapter(SourceAdapter):
    """Google/SERP jobs signal source (via approved SERP provider)."""

    name = SourceName.SERP_JOBS
    source_type = "serp"
    access_method = AccessMethod.MOCK
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    required_credentials = ["serp_api_key"]
    legal_note = "Google Jobs via approved SERP provider. AMBER: enable + sign off."

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        return
        yield  # pragma: no cover

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        if stable_unit(company.company_id, "serp") >= 0.35:
            return ExtractionResult.empty()
        ctx.audit(f"serp:jobs?q={company.name}", status="ok", records_found=1)
        ctx.record_usage("serp", "jobs.search", unit_cost=0.005)
        signal = ExtractedHiringSignal(
            source="serp_jobs",
            signal_type=HiringSignalType.JOB_POSTING,
            source_url="https://www.google.com/search?q=jobs",
            job_title="Accountant / Audit Associate",
            location=company.city or "Ahmedabad",
            posted_at=utcnow() - timedelta(days=int(20 * stable_unit(company.company_id, "serpd"))),
            description_excerpt="Public job posting indexed via SERP jobs.",
            confidence_score=0.6,
        )
        return ExtractionResult(hiring_signals=[signal])
