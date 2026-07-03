"""SerpJobsAdapter (GREEN provider) — REAL Google Jobs discovery via a SERP API.

Spec §8 "Source: Google Jobs / SERP Jobs":
- Use a SERP API or approved provider for job discovery.
- Use this for talent/hiring signal mining.
- Capture job title, company, location, posted date, source URL, description
  excerpt.
- Use as a signal that a company is hiring, NOT as a guaranteed contact source.

This adapter is the REAL slot for ``SourceName.SERP_JOBS``. It activates only when
``SERP_API_KEY`` resolves (registry real-vs-mock gate); with no key / demo mode the
registry serves ``MockSerpJobsAdapter`` instead.

Signal source, not a company source
------------------------------------
``discover()`` yields NO companies (SERP jobs never introduces new firms into the
pipeline). Instead the signal runs in the job's SIGNAL stage: the task layer
(``run_job_signals``) calls ``extract(company, ctx)`` per company already in the
pipeline. We query ``"<company> <city>"`` on Google Jobs and return
``ExtractedHiringSignal`` records (``signal_type=JOB_POSTING``), which the task
layer stores as ``HiringSignal`` back-matched by company name + location.

Generic provider driver
-----------------------
One driver keyed by ``settings.serp_provider``:
- ``"serpapi"`` -> GET https://serpapi.com/search.json?engine=google_jobs
- ``"serper"``  -> POST https://google.serper.dev/search  (google_jobs vertical)

Both provider responses normalize through ``_map_jobs`` to the same
``ExtractedHiringSignal`` shape. Every search is audited + metered (one
``serp_jobs.search`` unit per query). 429 / 5xx surface as ``ProviderRateLimited``
(transient); a throttled query returns no signals rather than failing the job.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.adapters._http import ProviderError, audited_request
from app.adapters.base import (
    CompanyRef,
    DiscoveredCompany,
    ExtractedHiringSignal,
    ExtractionResult,
    JobSpec,
    SourceAdapter,
)
from app.config import get_settings
from app.constants import AccessMethod, HiringSignalType, Posture, SourceName
from app.db import utcnow

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["SerpJobsAdapter", "SERPAPI_URL", "SERPER_URL"]

SERPAPI_URL = "https://serpapi.com/search.json"
SERPER_URL = "https://google.serper.dev/search"

# Approx per-search list price (USD) for the SERP provider, tracked for the
# job's estimated-cost preview (spec §7 preview panel / §8 cost limits).
_UNIT_COST = 0.005

# Cap description excerpts so we store a signal, not a full JD (spec §8: excerpt).
_EXCERPT_MAX = 280

# Relative "posted_at" strings ("3 days ago", "12 hours ago") -> a timedelta unit.
_REL_UNITS: dict[str, timedelta] = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}
_REL_RE = re.compile(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago", re.IGNORECASE)


def _excerpt(text: str | None) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= _EXCERPT_MAX:
        return collapsed
    return collapsed[: _EXCERPT_MAX - 1].rstrip() + "…"


def _parse_posted_at(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Resolve a Google-Jobs ``posted_at`` string to an absolute UTC datetime.

    Handles the relative form both providers emit ("3 days ago", "12 hours ago",
    "Just posted"/"Today" -> now). Returns ``None`` when unparseable so the signal
    still stores with a null ``posted_at`` rather than a bogus date.
    """
    if not value:
        return None
    base = now or utcnow()
    text = value.strip().lower()
    if text in {"just posted", "today", "just now"}:
        return base
    if text == "yesterday":
        return base - timedelta(days=1)
    match = _REL_RE.search(text)
    if match:
        amount = int(match.group(1))
        unit = _REL_UNITS[match.group(2).lower()]
        return base - amount * unit
    # Absolute ISO-ish dates are uncommon here but supported best-effort.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _company_matches(job_company: str | None, wanted: str) -> bool:
    """Loose name match: the wanted firm name is a token-substring of the posting's.

    SERP results for ``"<company> <city>"`` can surface adjacent firms; we only
    keep postings whose company name shares the wanted name (case-insensitive
    substring either direction) so a signal is back-matched to the right firm.
    """
    if not job_company:
        return False
    a = " ".join(job_company.split()).casefold()
    b = " ".join(wanted.split()).casefold()
    return bool(b) and (b in a or a in b)


class SerpJobsAdapter(SourceAdapter):
    name = SourceName.SERP_JOBS
    source_type = "serp"
    access_method = AccessMethod.SERP
    posture = Posture.GREEN
    default_enabled = True
    requires_signoff = False
    required_credentials = ["SERP_API_KEY"]
    legal_note = (
        "Google Jobs via approved SERP provider (SerpApi / Serper). Public job "
        "postings used as a hiring SIGNAL only, never as a verified contact source."
    )

    # -- discover ----------------------------------------------------------- #

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        """No-op: SERP jobs is a SIGNAL source and introduces no new companies."""
        return
        yield  # pragma: no cover

    # -- extract (the signal path) ------------------------------------------ #

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        """Query Google Jobs for ``"<company> <city>"`` and map JOB_POSTING signals.

        A throttled/failed search returns an empty result (the job continues); the
        HTTP helper has already audited the error. Non-matching postings (adjacent
        firms surfaced by the query) are dropped so signals back-match the firm.
        """
        settings = get_settings()
        api_key = settings.serp_api_key
        if not api_key:  # resolver should prevent this, but stay defensive.
            return ExtractionResult.empty()

        query = " ".join(p for p in (company.name, company.city) if p).strip()
        if not query:
            return ExtractionResult.empty()

        provider = (settings.serp_provider or "serpapi").strip().lower()
        try:
            raw_jobs = await self._run_search(provider, query, api_key, ctx)
        except ProviderError:
            # Transient (429/5xx) or permanent (4xx/bad payload): audited already.
            return ExtractionResult.empty()

        ctx.record_usage("serp_jobs", "jobs.search", unit_cost=_UNIT_COST)

        signals = self._map_jobs(provider, raw_jobs, company)
        return ExtractionResult(hiring_signals=signals)

    # -- provider drivers --------------------------------------------------- #

    async def _run_search(
        self, provider: str, query: str, api_key: str, ctx: SourceRunContext
    ) -> list[dict[str, Any]]:
        """Dispatch to the provider driver and return its raw job-result list."""
        if provider == "serper":
            return await self._search_serper(query, api_key, ctx)
        # Default / "serpapi": Google Jobs engine on SerpApi.
        return await self._search_serpapi(query, api_key, ctx)

    async def _search_serpapi(
        self, query: str, api_key: str, ctx: SourceRunContext
    ) -> list[dict[str, Any]]:
        params = {"engine": "google_jobs", "q": query, "api_key": api_key}
        # Audit trail must not leak the key: strip api_key from the audited URL.
        audit_url = f"{SERPAPI_URL}?engine=google_jobs&q={query}"
        response = await audited_request(
            ctx,
            "GET",
            SERPAPI_URL,
            audit_url=audit_url,
            params=params,
        )
        body = response.json()
        return list(body.get("jobs_results") or [])

    async def _search_serper(
        self, query: str, api_key: str, ctx: SourceRunContext
    ) -> list[dict[str, Any]]:
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": query, "type": "search", "engine": "google_jobs"}
        response = await audited_request(
            ctx,
            "POST",
            SERPER_URL,
            audit_url=f"{SERPER_URL}?q={query}",
            headers=headers,
            json=payload,
        )
        body = response.json()
        return list(body.get("jobs") or [])

    # -- normalization ------------------------------------------------------ #

    def _map_jobs(
        self, provider: str, raw_jobs: list[dict[str, Any]], company: CompanyRef
    ) -> list[ExtractedHiringSignal]:
        now = utcnow()
        signals: list[ExtractedHiringSignal] = []
        for row in raw_jobs:
            job_company = row.get("company_name") or row.get("company")
            if not _company_matches(job_company, company.name):
                continue
            title = row.get("title")
            location = row.get("location") or company.city
            posted_raw = self._posted_raw(row)
            source_url = self._source_url(row)
            signals.append(
                ExtractedHiringSignal(
                    source="serp_jobs",
                    signal_type=HiringSignalType.JOB_POSTING,
                    source_url=source_url,
                    job_title=title,
                    location=location,
                    posted_at=_parse_posted_at(posted_raw, now=now),
                    description_excerpt=_excerpt(row.get("description")),
                    confidence_score=0.6,
                )
            )
        return signals

    @staticmethod
    def _posted_raw(row: dict[str, Any]) -> str | None:
        # SerpApi nests it under detected_extensions.posted_at; Serper is flat.
        detected = row.get("detected_extensions") or {}
        return detected.get("posted_at") or row.get("postedAt") or row.get("posted_at")

    @staticmethod
    def _source_url(row: dict[str, Any]) -> str | None:
        # Serper is flat (``link``); SerpApi carries a list of apply options.
        if row.get("link"):
            return row["link"]
        for opt in row.get("apply_options") or []:
            if opt.get("link"):
                return opt["link"]
        return row.get("share_link")
