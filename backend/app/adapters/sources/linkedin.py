"""LinkedInAdapter (RED) — official-connector STUB. Disabled by default.

Spec §8 "Source: LinkedIn":
- Disabled by default.
- Do NOT scrape LinkedIn profiles, company pages, jobs, or authenticated content.
- Implement ONLY official/authorized access IF available to the customer.
- Show a red compliance warning; require admin/legal sign-off before enabling.
- Do NOT ask for personal LinkedIn credentials. Do NOT automate login.

This class is the REAL slot for ``SourceName.LINKEDIN``. It is a deliberate STUB:
the interface exists so a future OFFICIAL LinkedIn connector (Marketing / Sales
Navigator / an authorized partner API the tenant is entitled to) can be dropped in
here. Until such official access is wired, EVERY entry point is unavailable:

- ``discover()`` immediately raises ``SourceUnavailableError`` with the message
  "official LinkedIn API access not configured; scraping is not supported".
- ``extract()`` NEVER scrapes — it returns an empty result.

There is NO code path in this adapter that:
- opens an httpx client,
- touches ``linkedin.com`` (or any auth/login URL),
- reads LinkedIn credentials,
- automates a login.

Proof: this module imports no HTTP client and contains no ``linkedin.com`` URL; a
test asserts ``discover()`` always raises and that no ``linkedin.com`` /
``facebook.com`` host is ever requested.
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
    SourceUnavailable,
)
from app.adapters.sources._provider_base import SourceUnavailableError
from app.constants import AccessMethod, Posture, SourceName

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["LinkedInAdapter", "LINKEDIN_UNAVAILABLE_REASON"]

# The single, stable reason surfaced everywhere LinkedIn is asked to run.
LINKEDIN_UNAVAILABLE_REASON = (
    "official LinkedIn API access not configured; scraping is not supported"
)


class LinkedInAdapter(SourceAdapter):
    """RED official-connector stub — always unavailable until official access lands."""

    name = SourceName.LINKEDIN
    source_type = "official_connector"
    access_method = AccessMethod.OFFICIAL_API
    posture = Posture.RED
    default_enabled = False
    requires_signoff = True
    required_credentials: list[str] = []
    legal_note = (
        "LinkedIn ONLY via official/authorized access. RED: disabled by default; "
        "admin/legal sign-off required. NO scraping of profiles, company pages, "
        "jobs, or authenticated content; NO login automation; NO personal "
        "credentials. Official connector not yet configured — always unavailable."
    )

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        """Always unavailable: no official connector, and scraping is not supported.

        Raises ``SourceUnavailableError`` before any network access. The worker
        logs a skipped SourceRun and the mining job continues.
        """
        raise SourceUnavailableError(
            SourceUnavailable(self.name.value, LINKEDIN_UNAVAILABLE_REASON, self.posture)
        )
        # Unreachable; present only so the method is a valid async generator.
        yield  # pragma: no cover

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        """Never scrapes LinkedIn. Returns an empty result unconditionally."""
        return ExtractionResult.empty()
