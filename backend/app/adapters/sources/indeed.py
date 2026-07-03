"""IndeedAdapter (AMBER) — REAL, approved-provider-only HIRING-SIGNAL source.

Spec §8 "Source: Indeed":
- Use ONLY official API / licensed provider / approved data provider.
- Do NOT build uncontrolled credentialed scraping.
- Compliance-gated and disabled by default.

REAL slot for ``SourceName.INDEED``. Indeed data normalizes into HIRING SIGNALS
(``ExtractedHiringSignal``), not verified contacts: a company appearing in Indeed
job results is a hiring signal, not a guaranteed lead. NO first-party scraping is
shipped; it only queries the tenant's admin-configured approved provider. With no
provider configured, it raises ``SourceUnavailableError`` and the job continues.
"""

from __future__ import annotations

from app.adapters.sources._provider_base import HiringSignalProviderAdapter
from app.constants import Posture, SourceName

__all__ = ["IndeedAdapter"]


class IndeedAdapter(HiringSignalProviderAdapter):
    name = SourceName.INDEED
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    search_path = "/jobs/search"
    legal_note = (
        "Indeed via official API / approved provider ONLY. AMBER: disabled by "
        "default; enable + compliance sign-off required. Results are HIRING "
        "SIGNALS, not verified contacts. No uncontrolled credentialed scraping."
    )
