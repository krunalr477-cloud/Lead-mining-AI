"""YellowPagesAdapter (AMBER) — REAL, licensed-provider-only directory source.

Spec §8 "Source: Yellow Pages and Clutch":
- Compliance-gated and disabled by default.
- Prefer a licensed data provider / official API / approved third-party provider.
- If scraping is not legally approved, show UNAVAILABLE and explain why.

This is the REAL slot for ``SourceName.YELLOW_PAGES``. It ships NO first-party
scraping: it only queries the tenant's admin-configured approved provider (see
``LicensedProviderAdapter``). With no provider configured, ``discover()`` raises
``SourceUnavailableError`` and the job continues (graceful failure).
"""

from __future__ import annotations

from app.adapters.sources._provider_base import LicensedProviderAdapter
from app.constants import Posture, SourceName

__all__ = ["YellowPagesAdapter"]


class YellowPagesAdapter(LicensedProviderAdapter):
    name = SourceName.YELLOW_PAGES
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    search_path = "/companies/search"
    legal_note = (
        "Yellow Pages via approved licensed provider ONLY. AMBER: disabled by "
        "default; enable + compliance sign-off required. No first-party scraping."
    )
