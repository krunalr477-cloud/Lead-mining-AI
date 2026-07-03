"""Registry real-vs-mock resolution proof — no network, no DB.

Proves the single resolution contract the four real adapters depend on:

- With the provider/source key present AND demo mode off, ``resolve_*`` returns
  the REAL adapter class.
- With no key (or DEMO_MODE on), it falls back to the always-available MOCK — so
  the demo path and any key-less deployment never touch the network.
- A gated (AMBER/RED) source without sign-off resolves to ``SourceUnavailable``
  (the job logs a skipped SourceRun and continues), regardless of keys.
"""

from __future__ import annotations

import pytest

from app.adapters.enrichment.rocketreach import RocketReachAdapter
from app.adapters.llm.groq import GroqScorer
from app.adapters.mock.company_websites import MockCompanyWebsitesAdapter
from app.adapters.mock.google_maps import MockGoogleMapsAdapter
from app.adapters.mock.providers import (
    MockGroqScorerAdapter,
    MockMillionVerifierAdapter,
    MockRocketReachAdapter,
)
from app.adapters.registry import get_registry
from app.adapters.sources.company_websites import CompanyWebsitesAdapter
from app.adapters.sources.google_maps import GoogleMapsAdapter
from app.adapters.validation.millionverifier import MillionVerifierAdapter
from app.config import get_settings
from app.constants import Posture, SourceName


@pytest.fixture
def registry():
    return get_registry()


def _reset():
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings():
    _reset()
    yield
    _reset()


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def test_google_maps_real_when_key_present(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ADAPTER_MODE", "auto")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "maps-test-key")
    _reset()

    resolved = registry.resolve_source(SourceName.GOOGLE_MAPS, enabled=True, signed_off=True)

    assert resolved.ok
    assert isinstance(resolved.adapter, GoogleMapsAdapter)


def test_google_maps_mock_when_no_key(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ADAPTER_MODE", "auto")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
    _reset()

    resolved = registry.resolve_source(SourceName.GOOGLE_MAPS, enabled=True, signed_off=True)

    assert resolved.ok
    assert isinstance(resolved.adapter, MockGoogleMapsAdapter)


def test_google_maps_mock_in_demo_mode_even_with_key(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "maps-test-key")
    _reset()

    resolved = registry.resolve_source(SourceName.GOOGLE_MAPS, enabled=True, signed_off=True)

    assert resolved.ok
    assert isinstance(resolved.adapter, MockGoogleMapsAdapter)


def test_company_websites_real_when_not_demo(registry, monkeypatch):
    # The crawler needs no credential — real iff mode allows (not demo).
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ADAPTER_MODE", "auto")
    _reset()

    resolved = registry.resolve_source(SourceName.COMPANY_WEBSITES, enabled=True, signed_off=True)

    assert resolved.ok
    assert isinstance(resolved.adapter, CompanyWebsitesAdapter)


def test_company_websites_mock_in_demo_mode(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    _reset()

    resolved = registry.resolve_source(SourceName.COMPANY_WEBSITES, enabled=True, signed_off=True)

    assert resolved.ok
    assert isinstance(resolved.adapter, MockCompanyWebsitesAdapter)


# --------------------------------------------------------------------------- #
# Gated source -> SourceUnavailable
# --------------------------------------------------------------------------- #


def test_gated_source_without_signoff_is_unavailable(registry, monkeypatch):
    # LinkedIn is AMBER/RED and requires sign-off; enabled but not signed off.
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ENABLE_LINKEDIN_CONNECTOR", "true")
    _reset()

    resolved = registry.resolve_source(SourceName.LINKEDIN, enabled=True, signed_off=False)

    assert not resolved.ok
    assert resolved.adapter is None
    assert resolved.unavailable is not None
    assert resolved.unavailable.posture in (Posture.AMBER, Posture.RED)


def test_gated_source_unavailable_when_flag_off(registry, monkeypatch):
    # Enabled + signed off but the global env flag is off -> unavailable.
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ENABLE_LINKEDIN_CONNECTOR", "false")
    _reset()

    resolved = registry.resolve_source(SourceName.LINKEDIN, enabled=True, signed_off=True)

    assert not resolved.ok
    assert resolved.unavailable is not None


def test_unknown_source_is_unavailable(registry):
    resolved = registry.resolve_source("not_a_real_source", enabled=True, signed_off=True)

    assert not resolved.ok
    assert resolved.unavailable is not None
    assert resolved.unavailable.posture == Posture.RED


# --------------------------------------------------------------------------- #
# Providers: enrichment / verifier / LLM
# --------------------------------------------------------------------------- #


def test_enrichment_real_when_key_present(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ADAPTER_MODE", "auto")
    monkeypatch.setenv("ROCKETREACH_API_KEY", "rr-test-key")
    _reset()

    assert isinstance(registry.enrichment_adapter(), RocketReachAdapter)


def test_enrichment_mock_when_no_key(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ROCKETREACH_API_KEY", "")
    _reset()

    assert isinstance(registry.enrichment_adapter(), MockRocketReachAdapter)


def test_enrichment_mock_in_demo_mode(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("ROCKETREACH_API_KEY", "rr-test-key")
    _reset()

    assert isinstance(registry.enrichment_adapter(), MockRocketReachAdapter)


def test_verifier_real_when_key_present(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ADAPTER_MODE", "auto")
    monkeypatch.setenv("MILLIONVERIFIER_API_KEY", "mv-test-key")
    _reset()

    assert isinstance(registry.verifier_adapter(), MillionVerifierAdapter)


def test_verifier_mock_when_no_key(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("MILLIONVERIFIER_API_KEY", "")
    _reset()

    assert isinstance(registry.verifier_adapter(), MockMillionVerifierAdapter)


def test_scorer_real_when_key_present(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ADAPTER_MODE", "auto")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    _reset()

    assert isinstance(registry.scorer_adapter(), GroqScorer)


def test_scorer_mock_when_no_key(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GROQ_API_KEY", "")
    _reset()

    assert isinstance(registry.scorer_adapter(), MockGroqScorerAdapter)


def test_scorer_mock_in_demo_mode(registry, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    _reset()

    assert isinstance(registry.scorer_adapter(), MockGroqScorerAdapter)
