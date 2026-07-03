"""Adapter registry — the single place workers ask "which adapter, and may it run?".

Responsibilities (spec §8):
- Own the catalog of source adapters + the enrichment / verifier / LLM providers.
- Resolve a source to a *ready-to-run* adapter OR a ``SourceUnavailable`` when the
  source is gated (AMBER/RED) and not enabled + signed off + globally flag-on.
  A gated/unavailable source never raises: the caller logs a skipped SourceRun and
  continues (graceful degradation).
- Build a ``SourceRunContext`` for a (job, source) so the adapter's audit + usage
  trail is structural.

Mode resolution: in demo mode (or when the mock override applies) every source
resolves to its mock adapter. Real adapters land in later phases; asking for one
here yields ``SourceUnavailable`` rather than a crash.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.adapters.base import SourceAdapter, SourceUnavailable
from app.adapters.context import SourceRunContext
from app.adapters.mock.company_websites import MockCompanyWebsitesAdapter
from app.adapters.mock.directories import MockDirectoriesAdapter
from app.adapters.mock.gated import (
    MockClutchAdapter,
    MockFacebookSignalsAdapter,
    MockIndeedAdapter,
    MockLinkedInAdapter,
    MockSerpJobsAdapter,
    MockYellowPagesAdapter,
)
from app.adapters.mock.google_maps import MockGoogleMapsAdapter
from app.adapters.mock.providers import (
    MockGroqScorerAdapter,
    MockMillionVerifierAdapter,
    MockRocketReachAdapter,
)
from app.config import AdapterMode, get_settings
from app.constants import Posture, SourceName

if TYPE_CHECKING:
    import redis
    from sqlalchemy.orm import Session

__all__ = [
    "AdapterRegistry",
    "ResolvedSource",
    "get_registry",
]


# Which env flag gates each non-GREEN source (spec §8). GREEN sources are always
# allowed; AMBER/RED need enablement + sign-off (DataSourceConfig) AND the flag.
_GATE_FLAG: dict[SourceName, str] = {
    SourceName.FACEBOOK_SIGNALS: "enable_facebook_signals",
    SourceName.LINKEDIN: "enable_linkedin_connector",
    SourceName.YELLOW_PAGES: "enable_compliance_gated_sources",
    SourceName.CLUTCH: "enable_compliance_gated_sources",
    SourceName.INDEED: "enable_compliance_gated_sources",
    SourceName.SERP_JOBS: "enable_compliance_gated_sources",
}

# The mock catalog, one instance per source (adapters are stateless).
_MOCK_SOURCES: dict[SourceName, SourceAdapter] = {
    SourceName.GOOGLE_MAPS: MockGoogleMapsAdapter(),
    SourceName.COMPANY_WEBSITES: MockCompanyWebsitesAdapter(),
    SourceName.DIRECTORIES: MockDirectoriesAdapter(),
    SourceName.YELLOW_PAGES: MockYellowPagesAdapter(),
    SourceName.CLUTCH: MockClutchAdapter(),
    SourceName.FACEBOOK_SIGNALS: MockFacebookSignalsAdapter(),
    SourceName.SERP_JOBS: MockSerpJobsAdapter(),
    SourceName.INDEED: MockIndeedAdapter(),
    SourceName.LINKEDIN: MockLinkedInAdapter(),
}


@dataclass(slots=True)
class ResolvedSource:
    """A source resolved for a job: either a runnable adapter or the reason not."""

    source_name: SourceName
    adapter: SourceAdapter | None
    unavailable: SourceUnavailable | None

    @property
    def ok(self) -> bool:
        return self.adapter is not None


class AdapterRegistry:
    """Stateless resolver over the mock catalog (real adapters wired later)."""

    def source_names(self) -> list[SourceName]:
        return list(_MOCK_SOURCES.keys())

    def adapter_card(self, source_name: SourceName | str) -> SourceAdapter:
        """The (mock) adapter instance for a source — its class attrs are the card."""
        name = SourceName(source_name)
        return _MOCK_SOURCES[name]

    # -- resolution --------------------------------------------------------- #

    def resolve_source(
        self,
        source_name: SourceName | str,
        *,
        enabled: bool,
        signed_off: bool,
    ) -> ResolvedSource:
        """Resolve a source for a job.

        ``enabled`` / ``signed_off`` come from the tenant's DataSourceConfig row.
        GREEN sources ignore both. AMBER/RED sources need enabled + signed_off +
        their global env flag; any missing gate yields ``SourceUnavailable``.
        """
        try:
            name = SourceName(source_name)
        except ValueError:
            return ResolvedSource(
                source_name=source_name,  # type: ignore[arg-type]
                adapter=None,
                unavailable=SourceUnavailable(str(source_name), "unknown source", Posture.RED),
            )

        adapter = _MOCK_SOURCES.get(name)
        if adapter is None:
            return ResolvedSource(
                name, None, SourceUnavailable(name.value, "no adapter registered", Posture.RED)
            )

        if adapter.posture == Posture.GREEN:
            return ResolvedSource(name, adapter, None)

        # Gated: require enable + sign-off + global env flag.
        settings = get_settings()
        flag_name = _GATE_FLAG.get(name)
        flag_on = bool(getattr(settings, flag_name)) if flag_name else False
        if not enabled:
            reason = "source not enabled for tenant"
        elif adapter.requires_signoff and not signed_off:
            reason = "source requires compliance sign-off"
        elif not flag_on:
            reason = f"global flag {flag_name} is off"
        else:
            return ResolvedSource(name, adapter, None)

        return ResolvedSource(name, None, SourceUnavailable(name.value, reason, adapter.posture))

    def mode_for(self, source_name: SourceName | str) -> AdapterMode:
        """Effective adapter mode (always MOCK in this phase / demo mode)."""
        settings = get_settings()
        override = settings.source_mode_override(str(source_name))
        if override is not None:
            return override
        if settings.demo_mode:
            return AdapterMode.MOCK
        return settings.adapter_mode

    # -- providers ---------------------------------------------------------- #

    def enrichment_adapter(self) -> MockRocketReachAdapter:
        return _ENRICHMENT

    def verifier_adapter(self) -> MockMillionVerifierAdapter:
        return _VERIFIER

    def scorer_adapter(self) -> MockGroqScorerAdapter:
        return _SCORER

    # -- context ------------------------------------------------------------ #

    def build_context(
        self,
        *,
        session: Session,
        redis_client: redis.Redis,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        adapter: SourceAdapter,
    ) -> SourceRunContext:
        """Construct the per-(job, source) execution context for an adapter."""
        return SourceRunContext(
            session=session,
            redis_client=redis_client,
            tenant_id=tenant_id,
            job_id=job_id,
            source_name=adapter.name.value,
            source_type=adapter.source_type,
            access_method=adapter.access_method,
            posture=adapter.posture,
        )


_ENRICHMENT = MockRocketReachAdapter()
_VERIFIER = MockMillionVerifierAdapter()
_SCORER = MockGroqScorerAdapter()
_REGISTRY = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    return _REGISTRY
