"""Integration / provider-credential endpoints (spec §17 — Integrations screen).

GET    /integrations                 provider connection cards (status + masked key)
PUT    /integrations/{provider}       store a tenant-supplied provider secret
DELETE /integrations/{provider}       remove a stored provider secret
POST   /integrations/{provider}/test  probe a provider connection

Card status is the effective provider mode unioned with any stored
IntegrationCredential row:
- ``live``           real key resolves AND DEMO_MODE is off
- ``mock``           env-key provider running mock (DEMO_MODE / no key)
- ``configured``     a tenant key is stored but the pipeline still runs mock
                     (DEMO_MODE on) — the key will be used once DEMO_MODE=false
- ``not_configured`` no env key and nothing stored

Full secrets are NEVER returned — only ``****last4``. Stored secrets are
Fernet-encrypted (versioned envelope) via ``app.services.credentials``.
"""

from __future__ import annotations

import time as _time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.db import utcnow
from app.deps import CurrentUser, SessionDep, TenantId, require
from app.models import IntegrationCredential, User
from app.schemas.auth import provider_modes
from app.schemas.settings import IntegrationOut, IntegrationSecretInput, IntegrationTestResult
from app.services.credentials import (
    PROVIDER_SPECS,
    CredentialValidationError,
    delete_credential,
    probe_provider,
    store_credential,
    stored_mask,
    validate_input,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

ReadActor = Annotated[User, Depends(require("dashboard:read"))]
WriteActor = Annotated[User, Depends(require("settings:manage"))]

# The provider catalog surfaced on the Integrations screen. ``mode_key`` links to
# the /me provider-mode map (None => provider has no key-gated live/mock mode,
# e.g. OAuth or licensed providers, which report "not_configured" until stored).
_CATALOG: list[tuple[str, str, str | None, str]] = [
    (
        "google_oauth",
        "Google OAuth",
        None,
        "Sign-in and Sheets/Gmail authorization for the tenant.",
    ),
    ("google_maps", "Google Maps", "google_maps", "Places, geocoding, and company discovery."),
    ("sheets", "Google Sheets", "sheets", "Sales-facing system of record mirror."),
    ("gmail", "Gmail", "gmail", "Outreach sending and bounce/reply monitoring."),
    ("rocketreach", "RocketReach", "rocketreach", "Contact enrichment (emails, titles)."),
    (
        "millionverifier",
        "MillionVerifier",
        "millionverifier",
        "Provider-grade email deliverability check.",
    ),
    ("groq", "Groq / LLM", "groq", "LLM confidence scoring for email validation."),
    ("serp", "SERP / Jobs", "serp", "Job discovery and hiring-signal mining."),
    (
        "approved_providers",
        "Approved data providers",
        None,
        "Licensed third-party datasets for gated sources.",
    ),
]

_CATALOG_INDEX = {row[0]: row for row in _CATALOG}


async def _credentials(
    session: SessionDep, tenant_id: uuid.UUID
) -> dict[str, IntegrationCredential]:
    rows = await session.scalars(
        select(IntegrationCredential).where(IntegrationCredential.tenant_id == tenant_id)
    )
    return {c.provider: c for c in rows}


def _status_for(
    mode_key: str | None, modes: dict[str, str], cred: IntegrationCredential | None
) -> str:
    """Resolve the card status.

    ``live`` / ``mock`` come from the env-driven provider mode for key-gated
    providers. When a tenant key is stored but the effective mode is still mock
    (DEMO_MODE on), the card reports ``configured`` so the operator sees the key
    landed and knows it activates once DEMO_MODE is off. Providers without an
    env-key mode (OAuth / licensed) are ``live`` only when an active credential
    is stored, else ``not_configured``.
    """
    stored = cred is not None and cred.status == "active" and bool(cred.encrypted_secret_reference)
    if mode_key is not None:
        mode = modes.get(mode_key, "mock")
        if mode == "live":
            return "live"
        # env mode is mock: surface a stored key as "configured".
        return "configured" if stored else "mock"
    return "live" if stored else "not_configured"


def _card(
    provider: str,
    label: str,
    mode_key: str | None,
    note: str,
    modes: dict[str, str],
    cred: IntegrationCredential | None,
) -> IntegrationOut:
    return IntegrationOut(
        provider=provider,
        display_name=label,
        status=_status_for(mode_key, modes, cred),
        masked_key=stored_mask(cred),
        last_verified_at=cred.last_verified_at if cred else None,
        note=note,
        scopes=cred.scopes if cred else None,
    )


@router.get("", response_model=list[IntegrationOut])
async def list_integrations(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> list[IntegrationOut]:
    modes = provider_modes()
    creds = await _credentials(session, tenant_id)
    return [
        _card(provider, label, mode_key, note, modes, creds.get(provider))
        for provider, label, mode_key, note in _CATALOG
    ]


def _require_known(provider: str) -> tuple[str, str, str | None, str]:
    row = _CATALOG_INDEX.get(provider)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown provider: {provider}"
        )
    return row


@router.put("/{provider}", response_model=IntegrationOut)
async def put_integration(
    provider: str,
    body: IntegrationSecretInput,
    _actor: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
    _perm: WriteActor,
) -> IntegrationOut:
    """Store a tenant-supplied secret for a provider (encrypted at rest).

    The response carries only the masked hint — the plaintext is never echoed.
    """
    _p, label, mode_key, note = _require_known(provider)
    spec = PROVIDER_SPECS.get(provider)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider {provider} does not accept a stored key.",
        )
    try:
        cleaned = validate_input(spec, body.model_dump())
    except CredentialValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    cred = await store_credential(session, tenant_id=tenant_id, provider=provider, fields=cleaned)
    modes = provider_modes()
    return _card(provider, label, mode_key, note, modes, cred)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_integration(
    provider: str,
    _actor: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
    _perm: WriteActor,
) -> Response:
    """Remove a stored provider secret. Idempotent — 204 whether or not one
    existed (a missing key is already the desired state)."""
    _require_known(provider)
    await delete_credential(session, tenant_id=tenant_id, provider=provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider}/test", response_model=IntegrationTestResult)
async def test_integration(
    provider: str,
    _actor: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
    _perm: WriteActor,
) -> IntegrationTestResult:
    _require_known(provider)
    start = _time.perf_counter()
    creds = await _credentials(session, tenant_id)
    cred = creds.get(provider)
    result = await probe_provider(session, tenant_id=tenant_id, provider=provider, row=cred)
    # Record a successful probe on the credential row if one exists.
    if cred is not None and result.ok:
        cred.last_verified_at = utcnow()
        await session.commit()
    latency = int((_time.perf_counter() - start) * 1000)
    return IntegrationTestResult(
        ok=result.ok,
        provider=provider,
        status=result.status,
        message=result.message,
        latency_ms=latency,
    )
