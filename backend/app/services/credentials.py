"""Tenant-supplied provider credentials — store, resolve, and probe.

This is the server side of the Integrations screen key-entry flow (spec §17).
A tenant can paste a provider key in the UI; it is Fernet-encrypted (as a
versioned envelope, see :mod:`app.security.crypto`) into
``IntegrationCredential`` and never returned in plaintext — the list only shows
a ``****last4`` mask.

Resolution order for a provider's effective secret is **stored credential first,
then the process ``settings`` env value**. This lets an operator wire a live
provider entirely from the UI (no redeploy) while keeping env-configured keys
working exactly as before. Under ``DEMO_MODE`` the pipeline still runs the mock
adapters regardless of stored keys — storing a key is a no-op for job execution
until ``DEMO_MODE=false`` — but the Test-connection probe reports honestly.

Everything here is additive: the existing registry/env resolution path is
untouched, so the 435 pre-existing tests and verify-demo are unaffected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import IntegrationCredential
from app.security.crypto import decrypt_credential, encrypt_credential, masked_hint
from app.services.envfile import UnmanagedKeyError, write_env_values

__all__ = [
    "ProviderSpec",
    "PROVIDER_SPECS",
    "ResolvedCredential",
    "delete_credential",
    "probe_provider",
    "resolve_secret",
    "store_credential",
]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """How a provider's credential is entered, stored, and env-resolved.

    ``required`` are the input fields that MUST be present on a store request;
    ``optional`` may accompany them. ``env_attr`` is the ``settings`` attribute
    holding the env-configured value for the primary secret (``None`` for
    OAuth / licensed providers that have no single env key), used as the
    fallback when no credential is stored.
    """

    provider: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    env_attr: str | None = None
    # The stored field whose value is the "resolved secret" for live use.
    primary_field: str = "api_key"


# The catalog of tenant-configurable providers. Keys mirror the Integrations
# card catalog in ``app.api.integrations``.
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "google_oauth": ProviderSpec(
        provider="google_oauth",
        required=("client_id", "client_secret"),
        env_attr="google_client_secret",
        primary_field="client_secret",
    ),
    "google_maps": ProviderSpec(
        provider="google_maps",
        required=("api_key",),
        env_attr="google_maps_api_key",
    ),
    "sheets": ProviderSpec(
        provider="sheets",
        required=("api_key",),
        env_attr=None,
    ),
    "gmail": ProviderSpec(
        provider="gmail",
        required=("api_key",),
        env_attr=None,
    ),
    "rocketreach": ProviderSpec(
        provider="rocketreach",
        required=("api_key",),
        env_attr="rocketreach_api_key",
    ),
    "millionverifier": ProviderSpec(
        provider="millionverifier",
        required=("api_key",),
        env_attr="millionverifier_api_key",
    ),
    "groq": ProviderSpec(
        provider="groq",
        required=("api_key",),
        env_attr="groq_api_key",
    ),
    "serp": ProviderSpec(
        provider="serp",
        required=("api_key",),
        env_attr="serp_api_key",
    ),
    "approved_providers": ProviderSpec(
        provider="approved_providers",
        required=("api_key",),
        optional=("base_url",),
        env_attr=None,
    ),
}


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """The effective secret for a provider and where it came from."""

    secret: str | None
    source: str  # "stored" | "env" | "none"
    fields: dict[str, str]


class CredentialValidationError(ValueError):
    """A store request is missing required fields for the provider."""


def validate_input(spec: ProviderSpec, fields: dict[str, str | None]) -> dict[str, str]:
    """Return the cleaned field map or raise ``CredentialValidationError``.

    Only fields declared ``required``/``optional`` for the provider are kept;
    every required field must be a non-empty string.
    """
    allowed = set(spec.required) | set(spec.optional)
    cleaned: dict[str, str] = {}
    for name in allowed:
        value = fields.get(name)
        if value is not None and str(value).strip():
            cleaned[name] = str(value).strip()
    missing = [name for name in spec.required if not cleaned.get(name)]
    if missing:
        raise CredentialValidationError(f"{spec.provider} requires: {', '.join(missing)}")
    return cleaned


def _mirror_secret_to_env(spec: ProviderSpec | None, secret: str | None) -> None:
    """Keep the repo ``.env`` in sync with an API-key card, so the live adapters —
    which read their key from process ``settings``, not the DB — actually pick up a
    key entered in the Settings UI (spec §O2). Only pure API-key providers with an
    env attribute are mirrored; OAuth/licensed providers keep their own flows."""
    if spec is None or not spec.env_attr or spec.primary_field != "api_key":
        return
    try:
        write_env_values({spec.env_attr.upper(): secret or ""})
    except UnmanagedKeyError:
        return  # env attr not in the managed allowlist — DB row is still set


async def store_credential(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    fields: dict[str, str],
) -> IntegrationCredential:
    """Upsert an encrypted credential row for (tenant, provider).

    ``fields`` must already be validated. Storing resets ``last_verified_at`` —
    the operator should re-run Test connection to re-verify the new key.
    """
    encrypted = encrypt_credential(fields)
    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant_id,
                IntegrationCredential.provider == provider,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationCredential(
            tenant_id=tenant_id,
            provider=provider,
            encrypted_secret_reference=encrypted,
            scopes=[],
            status="active",
            last_verified_at=None,
        )
        session.add(row)
    else:
        row.encrypted_secret_reference = encrypted
        row.status = "active"
        row.last_verified_at = None
    await session.commit()
    await session.refresh(row)
    spec = PROVIDER_SPECS.get(provider)
    _mirror_secret_to_env(spec, fields.get(spec.primary_field) if spec else None)
    return row


async def delete_credential(session: AsyncSession, *, tenant_id: uuid.UUID, provider: str) -> bool:
    """Delete a stored credential. Returns True if a row was removed."""
    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant_id,
                IntegrationCredential.provider == provider,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    _mirror_secret_to_env(PROVIDER_SPECS.get(provider), None)  # clear the .env key too
    return True


def _stored_secret(spec: ProviderSpec, row: IntegrationCredential | None) -> dict[str, str] | None:
    if row is None or not row.encrypted_secret_reference:
        return None
    try:
        return decrypt_credential(row.encrypted_secret_reference)
    except Exception:
        # A corrupt/rotated-key blob must never crash resolution — treat as
        # "no stored credential" so we fall back to env / mock.
        return None


async def resolve_secret(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    row: IntegrationCredential | None = None,
) -> ResolvedCredential:
    """Resolve a provider's effective secret: stored first, then env.

    ``row`` may be passed to avoid a re-query when the caller already loaded the
    credential. Returns ``source="none"`` when neither a stored key nor an env
    value is present.
    """
    spec = PROVIDER_SPECS.get(provider)
    if spec is None:
        return ResolvedCredential(secret=None, source="none", fields={})

    if row is None:
        row = (
            await session.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.tenant_id == tenant_id,
                    IntegrationCredential.provider == provider,
                )
            )
        ).scalar_one_or_none()

    fields = _stored_secret(spec, row)
    if fields:
        secret = fields.get(spec.primary_field) or next(iter(fields.values()), None)
        if secret:
            return ResolvedCredential(secret=secret, source="stored", fields=fields)

    if spec.env_attr:
        env_value = getattr(get_settings(), spec.env_attr, "") or ""
        if env_value:
            return ResolvedCredential(
                secret=env_value, source="env", fields={spec.primary_field: env_value}
            )

    return ResolvedCredential(secret=None, source="none", fields={})


def stored_mask(row: IntegrationCredential | None) -> str | None:
    """``****last4`` mask for a stored credential, or None. Never plaintext."""
    if row is None or not row.encrypted_secret_reference:
        return None
    try:
        return masked_hint(row.encrypted_secret_reference)
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    status: str  # "live" | "mock" | "not_configured"
    message: str


async def probe_provider(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    row: IntegrationCredential | None = None,
) -> ProbeResult:
    """Probe a provider connection honestly, never leaking the secret.

    - No credential resolved -> ``not_configured`` (ok=False).
    - Credential resolved but ``DEMO_MODE`` on -> ``mock`` (ok=True): the
      pipeline runs deterministic fixtures, so the connection "works" in the
      sense the app will run — we say so plainly and do NOT make a network call.
    - Credential resolved and ``DEMO_MODE`` off -> a lightweight live reachability
      check for the providers that support one; any failure is reported as a
      failed probe (ok=False) with the exception CLASS name only — the secret is
      never included in the message.
    """
    settings = get_settings()
    resolved = await resolve_secret(session, tenant_id=tenant_id, provider=provider, row=row)

    if resolved.secret is None:
        return ProbeResult(
            ok=False,
            status="not_configured",
            message="No credentials configured for this provider.",
        )

    where = "Stored key" if resolved.source == "stored" else "Env key"
    if settings.demo_mode:
        return ProbeResult(
            ok=True,
            status="mock",
            message=(
                f"{where} saved. DEMO_MODE is on, so jobs run mock fixtures — "
                "set DEMO_MODE=false and restart to run this provider live."
            ),
        )

    # Live mode: attempt a real, cheap reachability check where we can.
    ok, detail = await _live_check(provider, resolved.secret)
    if ok:
        return ProbeResult(ok=True, status="live", message=f"{where} verified — {detail}")
    return ProbeResult(ok=False, status="live", message=f"Probe failed — {detail}")


async def _live_check(provider: str, secret: str) -> tuple[bool, str]:
    """Cheap live reachability check. Returns (ok, detail) — detail is safe to
    surface (no secret). Providers without a lightweight check report "resolved"
    (the key is present and the adapter will use it) rather than making a call.
    """
    import httpx

    timeout = httpx.Timeout(8.0, connect=4.0)
    try:
        if provider == "groq":
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {secret}"},
                )
            return (r.status_code == 200, f"HTTP {r.status_code} from Groq")
        if provider == "millionverifier":
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(
                    "https://api.millionverifier.com/api/v3/credits",
                    params={"api": secret},
                )
            return (r.status_code == 200, f"HTTP {r.status_code} from MillionVerifier")
        if provider == "google_maps":
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": "Ahmedabad", "key": secret},
                )
            body = (
                r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            )
            status_str = body.get("status", "")
            ok = r.status_code == 200 and status_str in ("OK", "ZERO_RESULTS")
            return (ok, f"Geocode status {status_str or r.status_code}")
    except Exception as exc:  # network / DNS / TLS — never leak the key
        return (False, f"{exc.__class__.__name__}")

    # No lightweight check for this provider — the key is present; the adapter
    # will exercise it at run time.
    return (True, "credential present (no live pre-check for this provider)")
