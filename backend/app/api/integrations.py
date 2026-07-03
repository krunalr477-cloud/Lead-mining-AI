"""Integration / provider-credential endpoints (spec §17 — Integrations screen).

GET  /integrations                 provider connection cards (status + masked key)
POST /integrations/{provider}/test probe a provider connection

The card status comes from the effective provider mode (``live`` when the key
resolves and DEMO_MODE is off, else ``mock``) unioned with any stored
IntegrationCredential row (which supplies the masked key / scopes / verified-at).
Full secrets are never returned — only ``****last4``.
"""

from __future__ import annotations

import time as _time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.db import utcnow
from app.deps import CurrentUser, SessionDep, TenantId, require
from app.models import IntegrationCredential, User
from app.schemas.auth import provider_modes
from app.schemas.settings import IntegrationOut, IntegrationTestResult
from app.security.crypto import mask_secret

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
    if mode_key is not None:
        return modes.get(mode_key, "mock")
    # No env-key mode: live only when a credential is stored and active.
    if cred is not None and cred.status == "active":
        return "live"
    return "not_configured"


@router.get("", response_model=list[IntegrationOut])
async def list_integrations(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> list[IntegrationOut]:
    modes = provider_modes()
    creds = await _credentials(session, tenant_id)
    out: list[IntegrationOut] = []
    for provider, label, mode_key, note in _CATALOG:
        cred = creds.get(provider)
        masked = None
        if cred is not None and cred.encrypted_secret_reference:
            # Stored references are opaque; show a stable masked tail, never a secret.
            masked = mask_secret(cred.encrypted_secret_reference)
        out.append(
            IntegrationOut(
                provider=provider,
                display_name=label,
                status=_status_for(mode_key, modes, cred),
                masked_key=masked,
                last_verified_at=cred.last_verified_at if cred else None,
                note=note,
                scopes=cred.scopes if cred else None,
            )
        )
    return out


_CATALOG_INDEX = {row[0]: row for row in _CATALOG}


@router.post("/{provider}/test", response_model=IntegrationTestResult)
async def test_integration(
    provider: str,
    actor: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
    _perm: WriteActor,
) -> IntegrationTestResult:
    row = _CATALOG_INDEX.get(provider)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown provider: {provider}"
        )
    _, _label, mode_key, _note = row
    modes = provider_modes()
    start = _time.perf_counter()
    creds = await _credentials(session, tenant_id)
    cred = creds.get(provider)
    status_str = _status_for(mode_key, modes, cred)
    ok = status_str in ("live", "mock")
    if status_str == "live":
        message = "Live credentials resolved."
    elif status_str == "mock":
        message = "Running in mock mode — deterministic fixtures, no external call."
    else:
        message = "No credentials configured for this provider."
    # Record the probe on the credential row if one exists.
    if cred is not None and ok:
        cred.last_verified_at = utcnow()
        await session.commit()
    latency = int((_time.perf_counter() - start) * 1000)
    return IntegrationTestResult(
        ok=ok, provider=provider, status=status_str, message=message, latency_ms=latency
    )
