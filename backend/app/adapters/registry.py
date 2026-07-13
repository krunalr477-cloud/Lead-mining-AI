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
from app.adapters.enrichment.rocketreach import RocketReachAdapter
from app.adapters.llm.groq import GroqScorer
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
from app.adapters.sources.clutch import ClutchAdapter
from app.adapters.sources.company_websites import CompanyWebsitesAdapter
from app.adapters.sources.facebook_signals import FacebookSignalsAdapter
from app.adapters.sources.google_maps import GoogleMapsAdapter
from app.adapters.sources.indeed import IndeedAdapter
from app.adapters.sources.linkedin import LinkedInAdapter
from app.adapters.sources.serp_jobs import SerpJobsAdapter
from app.adapters.sources.yellow_pages import YellowPagesAdapter
from app.adapters.validation.millionverifier import MillionVerifierAdapter
from app.config import AdapterMode, get_settings
from app.constants import Posture, SourceName

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.adapters.base import (
        EmailVerifierAdapter,
        EnrichmentAdapter,
        LLMScorerAdapter,
    )

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


def _build_google_maps_real() -> SourceAdapter | None:
    """Real Google Maps adapter iff GOOGLE_MAPS_API_KEY resolves; else None."""
    key = get_settings().google_maps_api_key
    return GoogleMapsAdapter(api_key=key) if key else None


def _build_company_websites_real() -> SourceAdapter | None:
    """Real website crawler — no credential required (polite public HTTP crawl),
    so it always builds; the mode gate in _resolve_adapter decides real-vs-mock."""
    return CompanyWebsitesAdapter()


def _build_serp_jobs_real() -> SourceAdapter | None:
    """Real SERP-jobs signal adapter iff SERP_API_KEY resolves; else None.

    Gating (AMBER: enable + sign-off + enable_compliance_gated_sources) is decided
    off the mock card upstream in resolve_source; this factory only picks the REAL
    driver once the source is already permitted and a provider key is present."""
    return SerpJobsAdapter() if get_settings().serp_api_key else None


def _build_yellow_pages_real() -> SourceAdapter | None:
    """Real Yellow Pages adapter — licensed-provider-only. Always builds; the
    per-tenant provider connection is resolved from the DB at discover() time and
    yields SourceUnavailable when none is configured (no first-party scraping)."""
    return YellowPagesAdapter()


def _build_clutch_real() -> SourceAdapter | None:
    """Real Clutch adapter — licensed-provider-only (see _build_yellow_pages_real)."""
    return ClutchAdapter()


def _build_indeed_real() -> SourceAdapter | None:
    """Real Indeed adapter — approved-provider-only hiring signals; always builds,
    provider connection resolved per-tenant at run time (no scraping)."""
    return IndeedAdapter()


def _build_linkedin_real() -> SourceAdapter | None:
    """Real LinkedIn slot — official-connector STUB. Always builds; every entry
    point is unavailable until official access is configured (never scrapes)."""
    return LinkedInAdapter()


def _build_facebook_signals_real() -> SourceAdapter | None:
    """Real compliance-gated Facebook signals slot. Always builds; the three
    compliant modes (authorized Graph Page, SERP public-page discovery, SERP/careers
    hiring fallback) each resolve their access per-tenant at run time and fail
    GRACEFULLY (skip + continue) when no compliant access exists — never scrapes,
    never logs in, never touches private profiles/groups/Messenger."""
    return FacebookSignalsAdapter()


# The real catalog: SourceName -> (real factory | None, mock instance).
# The FIRST slot builds the REAL adapter (returning None when its required
# credentials don't resolve); the SECOND slot is the always-available mock.
# resolve_source() picks real vs mock by effective mode + credential presence.
SOURCE_ADAPTERS: dict[
    SourceName, tuple[Callable[[], SourceAdapter | None] | None, SourceAdapter]
] = {
    SourceName.GOOGLE_MAPS: (_build_google_maps_real, _MOCK_SOURCES[SourceName.GOOGLE_MAPS]),
    SourceName.COMPANY_WEBSITES: (
        _build_company_websites_real,
        _MOCK_SOURCES[SourceName.COMPANY_WEBSITES],
    ),
    SourceName.DIRECTORIES: (None, _MOCK_SOURCES[SourceName.DIRECTORIES]),
    SourceName.YELLOW_PAGES: (_build_yellow_pages_real, _MOCK_SOURCES[SourceName.YELLOW_PAGES]),
    SourceName.CLUTCH: (_build_clutch_real, _MOCK_SOURCES[SourceName.CLUTCH]),
    SourceName.FACEBOOK_SIGNALS: (
        _build_facebook_signals_real,
        _MOCK_SOURCES[SourceName.FACEBOOK_SIGNALS],
    ),
    SourceName.SERP_JOBS: (_build_serp_jobs_real, _MOCK_SOURCES[SourceName.SERP_JOBS]),
    SourceName.INDEED: (_build_indeed_real, _MOCK_SOURCES[SourceName.INDEED]),
    SourceName.LINKEDIN: (_build_linkedin_real, _MOCK_SOURCES[SourceName.LINKEDIN]),
}


# --------------------------------------------------------------------------- #
# Provider registries (enrichment / verifier / LLM) — same (real|None, mock)
# tuple shape as SOURCE_ADAPTERS. The FIRST slot is the REAL implementation; the
# SECOND is the always-available mock. resolve_* picks real vs mock by effective
# mode + whether the provider's required credential resolves in settings.
# --------------------------------------------------------------------------- #

# Provider required-credential -> settings attribute holding the key. The base
# adapters declare uppercase env-style names (ROCKETREACH_API_KEY); Settings uses
# the lowercased field, so we look the key up case-insensitively.
_MOCK_ENRICHMENT = MockRocketReachAdapter()
_MOCK_VERIFIER = MockMillionVerifierAdapter()
_MOCK_SCORER = MockGroqScorerAdapter()

ENRICHMENT_ADAPTERS: dict[str, tuple[EnrichmentAdapter | None, EnrichmentAdapter]] = {
    "rocketreach": (RocketReachAdapter(), _MOCK_ENRICHMENT),
}
VERIFIER_ADAPTERS: dict[str, tuple[EmailVerifierAdapter | None, EmailVerifierAdapter]] = {
    "millionverifier": (MillionVerifierAdapter(), _MOCK_VERIFIER),
}
LLM_ADAPTERS: dict[str, tuple[LLMScorerAdapter | None, LLMScorerAdapter]] = {
    "groq": (GroqScorer(), _MOCK_SCORER),
}


def _credentials_resolve(required: list[str]) -> bool:
    """True iff every required credential resolves to a non-empty settings value.

    Base adapters declare uppercase env names (e.g. ``ROCKETREACH_API_KEY``);
    Settings stores the lowercased field (``rocketreach_api_key``). We match on
    the lowercased name so real providers activate exactly when the user's key is
    present — and fall back to mock (DEMO_MODE / no key) otherwise.
    """
    settings = get_settings()
    for cred in required:
        value = getattr(settings, cred.lower(), None)
        if not value:
            return False
    return True


def _provider_mode() -> AdapterMode:
    """Effective provider mode: MOCK under demo mode, else the global adapter mode."""
    settings = get_settings()
    if settings.demo_mode:
        return AdapterMode.MOCK
    return settings.adapter_mode


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

        # The mock instance is the source *card* — posture / requires_signoff are
        # class attributes shared by the real and mock implementations, so gate
        # decisions read them off the always-present mock.
        card = _MOCK_SOURCES.get(name)
        if card is None:
            return ResolvedSource(
                name, None, SourceUnavailable(name.value, "no adapter registered", Posture.RED)
            )

        if card.posture == Posture.GREEN:
            return self._resolved_or_unavailable(name, card)

        # Gated: require enable + sign-off + global env flag.
        settings = get_settings()
        flag_name = _GATE_FLAG.get(name)
        flag_on = bool(getattr(settings, flag_name)) if flag_name else False
        if not enabled:
            reason = "source not enabled for tenant"
        elif card.requires_signoff and not signed_off:
            reason = "source requires compliance sign-off"
        elif not flag_on:
            reason = f"global flag {flag_name} is off"
        else:
            return self._resolved_or_unavailable(name, card)

        return ResolvedSource(name, None, SourceUnavailable(name.value, reason, card.posture))

    def _resolved_or_unavailable(self, name: SourceName, card: SourceAdapter) -> ResolvedSource:
        """Wrap _resolve_adapter: a None adapter becomes a skip, never a crash."""
        adapter = self._resolve_adapter(name, card)
        if adapter is None:
            return ResolvedSource(
                name,
                None,
                SourceUnavailable(
                    name.value,
                    "no live adapter — skipped (demo-only source or missing credentials)",
                    card.posture,
                ),
            )
        return ResolvedSource(name, adapter, None)

    def _resolve_adapter(self, name: SourceName, card: SourceAdapter) -> SourceAdapter | None:
        """Pick the adapter for the effective mode, or None when none may run.

        MOCK mode (demo mode, ADAPTER_MODE=mock, or a per-source override) always
        serves the mock. In REAL/AUTO mode the real factory decides: no factory
        registered (demo-only source like directories) or the factory returning
        None (missing credentials) yields None — the source is SKIPPED with an
        explicit event rather than silently substituting fabricated mock data
        into a real run (the bug that injected 134 fake companies into a real
        tenant's sheet).
        """
        entry = SOURCE_ADAPTERS.get(name)
        if entry is None:
            return card
        real_factory, mock = entry
        if self.mode_for(name) == AdapterMode.MOCK:
            return mock
        if real_factory is None:
            return None
        return real_factory()

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

    def enrichment_adapter(self, provider: str = "rocketreach") -> EnrichmentAdapter:
        """Resolve the enrichment provider: REAL when its key resolves + mode
        allows, else the mock."""
        return _resolve_provider(ENRICHMENT_ADAPTERS, provider, _MOCK_ENRICHMENT)

    def verifier_adapter(self, provider: str = "millionverifier") -> EmailVerifierAdapter:
        """Resolve the verifier provider (real MillionVerifier or mock)."""
        return _resolve_provider(VERIFIER_ADAPTERS, provider, _MOCK_VERIFIER)

    def scorer_adapter(self, provider: str = "groq") -> LLMScorerAdapter:
        """Resolve the LLM scorer provider (real Groq or heuristic mock)."""
        return _resolve_provider(LLM_ADAPTERS, provider, _MOCK_SCORER)

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


def _resolve_provider(registry, provider, default_mock):
    """Pick REAL vs mock for a provider registry entry.

    Real iff: the provider has a real implementation registered, the effective
    provider mode is not MOCK (i.e. not demo mode), AND the real adapter's
    required credentials resolve in settings. Otherwise the mock — so no-key /
    DEMO_MODE always serves the deterministic mock and never touches the network.
    """
    entry = registry.get(provider)
    if entry is None:
        return default_mock
    real, mock = entry
    if real is None:
        return mock
    if _provider_mode() == AdapterMode.MOCK:
        return mock
    if not _credentials_resolve(real.required_credentials):
        return mock
    return real


_REGISTRY = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    return _REGISTRY
