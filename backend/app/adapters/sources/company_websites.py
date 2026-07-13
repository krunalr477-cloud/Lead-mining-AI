"""CompanyWebsitesAdapter (GREEN) — REAL public-website crawler (spec §8
"Source: Company Websites", §9 Contact Extraction).

This is the REAL slot for ``SourceName.COMPANY_WEBSITES``. It requires no API
key (a polite HTTP crawl of public pages), so it activates whenever the registry
resolves REAL/AUTO mode and demo mode is off; DEMO_MODE serves
``MockCompanyWebsitesAdapter`` instead. All network access flows through the
``app.crawler`` package, which audits every fetch (including the robots probe)
via the SourceRunContext.

- ``discover`` yields nothing: this source only deep-dives companies already
  found by Maps / directories (passthrough), matching the mock's contract.
- ``extract`` crawls ``company.domain`` / ``company.website`` and returns a fully
  merged ``ExtractionResult`` (contacts with source_page + snippet + confidence,
  emails, phones, social links, about text, hiring signals, pages_crawled,
  website_status).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.adapters.base import (
    CompanyRef,
    DiscoveredCompany,
    ExtractionResult,
    JobSpec,
    SourceAdapter,
)
from app.constants import AccessMethod, Posture, SourceName
from app.crawler.extract import crawl_company

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["CompanyWebsitesAdapter"]


class CompanyWebsitesAdapter(SourceAdapter):
    name = SourceName.COMPANY_WEBSITES
    source_type = "crawler"
    access_method = AccessMethod.HTTP_CRAWL
    posture = Posture.GREEN
    default_enabled = True
    requires_signoff = False
    required_credentials: list[str] = []
    legal_note = (
        "Polite crawl of public company pages only. robots.txt is honored under "
        "the LeadMineBot token; page fetches use a standard browser User-Agent "
        "(bot-labeled UAs are blanket-blocked by common hosts). Per-domain rate "
        "limits and page/time caps apply. No authenticated or private content."
    )

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        # Passthrough: this source never independently discovers companies; it
        # only deep-dives ones already found. Yield nothing.
        return
        yield  # pragma: no cover - makes this an async generator

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        """Crawl the company's public website and return a merged result.

        Every page fetch (and the robots.txt probe) is audited by the crawler
        through ``ctx``; a crawl failure degrades to a website_status rather than
        raising, so the job continues (spec §8 graceful failure).
        """
        return await crawl_company(company, ctx)
