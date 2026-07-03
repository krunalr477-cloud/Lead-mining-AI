"""ClutchAdapter (AMBER) — REAL, licensed-provider-only B2B directory source.

Spec §8 "Source: Yellow Pages and Clutch":
- Compliance-gated and disabled by default.
- Prefer a licensed data provider / official API / approved third-party provider.
- If scraping is not legally approved, show UNAVAILABLE and explain why.

REAL slot for ``SourceName.CLUTCH``. NO first-party scraping: it only queries the
tenant's admin-configured approved provider (see ``LicensedProviderAdapter``).
With no provider configured, ``discover()`` raises ``SourceUnavailableError`` and
the job continues.
"""

from __future__ import annotations

from app.adapters.sources._provider_base import LicensedProviderAdapter
from app.constants import Posture, SourceName

__all__ = ["ClutchAdapter"]


class ClutchAdapter(LicensedProviderAdapter):
    name = SourceName.CLUTCH
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    search_path = "/providers/search"
    legal_note = (
        "Clutch via approved licensed provider ONLY. AMBER: disabled by default; "
        "enable + compliance sign-off required. No first-party scraping."
    )
