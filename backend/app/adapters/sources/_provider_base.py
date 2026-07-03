"""LicensedProviderAdapter — shared base for the compliance-gated directory sources.

Spec §8 "Yellow Pages and Clutch" / "Indeed":
- Compliance-gated and disabled by default.
- PREFER a licensed data provider / official API / approved third-party provider.
- If scraping is not legally approved, show UNAVAILABLE and explain why.

This base ships NO first-party scraping. It only ever talks to an *admin-configured
licensed provider endpoint*: the tenant supplies a ``base_url`` and ``api_key`` for
an approved provider, and the adapter GETs that provider's search endpoint and
normalizes the JSON into our ``DiscoveredCompany`` / ``ExtractedHiringSignal`` model.

Config resolution (per tenant, at run time)
-------------------------------------------
The provider connection lives in an ``IntegrationCredential`` row whose ``provider``
equals the source name (e.g. ``yellow_pages``). Its ``encrypted_secret_reference`` is
a Fernet-encrypted JSON blob::

    {"base_url": "https://api.approved-provider.example/v1", "api_key": "..."}

If no such credential is configured for the tenant (or it has no base_url/api_key),
``_provider_config`` returns ``None`` and the adapter raises ``SourceUnavailable`` —
the worker logs a skipped SourceRun and the mining job CONTINUES (graceful failure).

We deliberately resolve config from ``ctx`` (session + tenant) at ``discover()`` time
rather than at construction: the registry builds one stateless real adapter, and the
per-tenant provider connection is only known once a job's context exists. A
``FakeCtx`` in tests can override ``_provider_config`` directly to stay DB-free.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.adapters._http import ProviderError, ProviderRateLimited, audited_request
from app.adapters.base import (
    DiscoveredCompany,
    ExtractedHiringSignal,
    JobSpec,
    SourceAdapter,
    SourceUnavailable,
)
from app.constants import AccessMethod, HiringSignalType, Posture

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = [
    "LicensedProviderAdapter",
    "ProviderConfig",
]

# Approx per-search list cost for an approved licensed provider; tracked for the
# job cost estimate. Real pricing is provider-specific and admin-overridable.
_SEARCH_UNIT_COST = 0.01


@dataclass(slots=True)
class ProviderConfig:
    """A resolved licensed-provider connection for one tenant + source."""

    base_url: str
    api_key: str


class LicensedProviderAdapter(SourceAdapter):
    """Base for AMBER directory sources backed by an approved licensed provider.

    Subclasses set ``name`` / ``posture`` / ``legal_note`` and the provider
    ``search_path`` (the endpoint appended to the configured ``base_url``). NO
    first-party scraping is shipped: without an admin-configured provider the
    source is UNAVAILABLE.
    """

    source_type = "provider_api"
    access_method = AccessMethod.LICENSED_PROVIDER
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    required_credentials: list[str] = []

    # The provider search endpoint, appended to the configured base_url.
    search_path: str = "/search"

    # -- config resolution -------------------------------------------------- #

    def _provider_config(self, ctx: SourceRunContext) -> ProviderConfig | None:
        """Resolve the tenant's approved-provider connection for this source.

        Reads the ``IntegrationCredential`` row (provider == this source's name),
        decrypts its JSON secret, and returns ``base_url`` + ``api_key``. Returns
        ``None`` when nothing is configured — the caller then raises
        ``SourceUnavailable`` and the job continues.
        """
        # Local imports keep this module importable in DEMO_MODE deployments that
        # never touch the DB / crypto stack.
        from sqlalchemy import select

        from app.models import IntegrationCredential
        from app.security.crypto import get_cipher

        session = getattr(ctx, "session", None)
        tenant_id = getattr(ctx, "tenant_id", None)
        if session is None or tenant_id is None:
            return None

        credential = session.scalars(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant_id,
                IntegrationCredential.provider == self.name.value,
                IntegrationCredential.status == "active",
            )
        ).first()
        if credential is None:
            return None

        try:
            blob = get_cipher().decrypt(credential.encrypted_secret_reference)
            data = json.loads(blob)
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

        base_url = str(data.get("base_url") or "").strip().rstrip("/")
        api_key = str(data.get("api_key") or "").strip()
        if not base_url or not api_key:
            return None
        return ProviderConfig(base_url=base_url, api_key=api_key)

    # -- request building --------------------------------------------------- #

    def _params(self, job: JobSpec) -> dict[str, Any]:
        """Search query params for the licensed provider (override as needed)."""
        params: dict[str, Any] = {}
        query_parts = []
        if job.company_type:
            query_parts.append(job.company_type)
        if job.services:
            query_parts.extend(job.services[:3])
        if query_parts:
            params["q"] = " ".join(query_parts)
        if job.city:
            params["city"] = job.city
        if job.state:
            params["state"] = job.state
        if job.country:
            params["country"] = job.country
        return params

    async def _fetch(self, config: ProviderConfig, job: JobSpec, ctx: SourceRunContext) -> Any:
        """GET the provider search endpoint; audited + metered; returns JSON."""
        url = f"{config.base_url}{self.search_path}"
        # Key-free audit trail: the api_key rides in a header, never the audit URL.
        audit_url = f"{self.name.value}:provider_search {self.search_path}"
        headers = {"Authorization": f"Bearer {config.api_key}", "Accept": "application/json"}
        response = await audited_request(
            ctx,
            "GET",
            url,
            audit_url=audit_url,
            headers=headers,
            params=self._params(job),
        )
        ctx.record_usage(self.name.value, "provider.search", unit_cost=_SEARCH_UNIT_COST)
        return response.json()

    # -- discover ----------------------------------------------------------- #

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        """Yield normalized companies from the approved licensed provider.

        Raises ``SourceUnavailable`` (job continues) when no provider is
        configured. Transient provider failures yield nothing rather than
        crashing the job.
        """
        config = self._provider_config(ctx)
        if config is None:
            raise self._unavailable("no licensed provider configured")

        try:
            payload = await self._fetch(config, job, ctx)
        except ProviderRateLimited:
            return
        except ProviderError:
            return

        for row in self._iter_rows(payload):
            company = self._map_company(row)
            if company is not None:
                yield company

    # -- normalization ------------------------------------------------------ #

    @staticmethod
    def _iter_rows(payload: Any) -> list[dict[str, Any]]:
        """Pull the list of result records from a provider payload.

        Accepts either a bare list or a dict wrapping the list under a common key
        (``results`` / ``data`` / ``companies`` / ``items``).
        """
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            for key in ("results", "data", "companies", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [r for r in value if isinstance(r, dict)]
        return []

    def _map_company(self, row: dict[str, Any]) -> DiscoveredCompany | None:
        """Normalize one provider record into a ``DiscoveredCompany``."""
        name = _first(row, "name", "company_name", "title")
        if not name:
            return None
        website = _first(row, "website", "url", "site")
        return DiscoveredCompany(
            name=name,
            source_name=self.name.value,
            source_url=_first(row, "source_url", "profile_url", "listing_url"),
            website=website,
            domain=_first(row, "domain") or _domain_of(website),
            phone=_first(row, "phone", "phone_number", "telephone"),
            address=_first(row, "address", "formatted_address"),
            city=_first(row, "city", "locality"),
            state=_first(row, "state", "region"),
            country=_first(row, "country"),
            postal_code=_first(row, "postal_code", "zip", "zipcode"),
            industry=_first(row, "industry", "category"),
            description=_first(row, "description", "summary"),
            company_size=_first(row, "company_size", "size", "employees"),
            raw_payload={"provider": self.name.value, "licensed": True},
            is_demo=False,
        )

    # -- helpers ------------------------------------------------------------ #

    def _unavailable(self, reason: str) -> SourceUnavailableError:
        return SourceUnavailableError(SourceUnavailable(self.name.value, reason, self.posture))


class SourceUnavailableError(Exception):
    """Raised by a real adapter when it cannot run; carries a ``SourceUnavailable``.

    The worker catches this, logs a skipped SourceRun and continues (spec §8). It
    wraps the ``SourceUnavailable`` dataclass so the reason/posture reach the run.
    """

    def __init__(self, detail: SourceUnavailable) -> None:
        self.detail = detail
        super().__init__(f"{detail.source_name} unavailable: {detail.reason}")


def _first(row: dict[str, Any], *keys: str) -> str | None:
    """First non-empty string value among ``keys`` in ``row``."""
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _domain_of(url: str | None) -> str | None:
    """Bare registrable host from a URL (scheme/``www.``/path stripped)."""
    if not url:
        return None
    from urllib.parse import urlsplit

    candidate = url if "//" in url else f"//{url}"
    host = (urlsplit(candidate).hostname or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


class HiringSignalProviderAdapter(LicensedProviderAdapter):
    """Base for provider-backed HIRING-SIGNAL sources (Indeed).

    Same provider-config resolution as the directory base, but the provider's job
    listings normalize into ``ExtractedHiringSignal`` records rather than new
    companies. ``discover()`` yields no companies (signals attach per-company at
    ``extract()`` in a later phase; this adapter exposes the normalizer + a
    signal-yielding search for the worker/tests).
    """

    search_path = "/jobs/search"

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        # A hiring-signal source discovers no NEW companies; it enriches known
        # ones with signals. Guard that the provider IS configured (else the job
        # should record the source as unavailable) then yield nothing.
        config = self._provider_config(ctx)
        if config is None:
            raise self._unavailable("no licensed provider configured")
        return
        yield  # pragma: no cover

    async def search_signals(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> list[ExtractedHiringSignal]:
        """Fetch job postings from the approved provider as hiring signals.

        Raises ``SourceUnavailableError`` when no provider is configured; returns
        an empty list on transient provider failures.
        """
        config = self._provider_config(ctx)
        if config is None:
            raise self._unavailable("no licensed provider configured")
        try:
            payload = await self._fetch(config, job, ctx)
        except ProviderRateLimited:
            return []
        except ProviderError:
            return []

        signals: list[ExtractedHiringSignal] = []
        for row in self._iter_rows(payload):
            signal = self._map_signal(row)
            if signal is not None:
                signals.append(signal)
        return signals

    def _map_signal(self, row: dict[str, Any]) -> ExtractedHiringSignal | None:
        """Normalize one provider job record into an ``ExtractedHiringSignal``."""
        title = _first(row, "job_title", "title", "position")
        if not title:
            return None
        return ExtractedHiringSignal(
            source=self.name.value,
            signal_type=HiringSignalType.JOB_POSTING,
            source_url=_first(row, "source_url", "url", "job_url"),
            job_title=title,
            location=_first(row, "location", "city", "job_location"),
            posted_at=None,
            description_excerpt=_first(row, "description", "snippet", "summary"),
            confidence_score=0.6,
        )
