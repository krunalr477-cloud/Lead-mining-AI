"""Tenant settings + validation-rules endpoints (spec §17 — Settings screens).

GET   /settings           tenant campaign / send-window blob
PATCH /settings           partial update of that blob
GET   /validation-rules   the knobs gating Sales_Ready_Leads (frontend-shaped)
PATCH /validation-rules   partial update

The validation-rules view exposes frontend field names that differ from the keys
the pipeline reads off the JSONB. GET maps DB -> frontend; PATCH writes BOTH the
frontend keys and the pipeline keys so validation.py keeps reading correct values.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from starlette.concurrency import run_in_threadpool

from app.constants import DEFAULT_ROLE_KEYWORDS
from app.deps import SessionDep, TenantId, require
from app.models import (
    AuditLog,
    CampaignSettings,
    User,
    ValidationRuleSet,
    default_validation_rules,
)
from app.schemas.settings import (
    EnvKeyOut,
    EnvKeyReveal,
    EnvKeyRevealRequest,
    EnvKeyUpdate,
    SettingsOut,
    SettingsPatch,
    ValidationRulesOut,
    ValidationRulesPatch,
)
from app.security.crypto import mask_secret
from app.services.envfile import (
    MANAGED_ENV_KEYS,
    UnmanagedKeyError,
    managed_key,
    read_env,
    write_env_values,
)

router = APIRouter(tags=["settings"])

ReadActor = Annotated[User, Depends(require("dashboard:read"))]
WriteActor = Annotated[User, Depends(require("settings:manage"))]


# --------------------------------------------------------------------------- #
# /settings — campaign / send-window blob (backed by CampaignSettings)
# --------------------------------------------------------------------------- #


async def _get_campaign_settings(session: SessionDep, tenant_id: uuid.UUID) -> CampaignSettings:
    cs = await session.scalar(
        select(CampaignSettings).where(CampaignSettings.tenant_id == tenant_id)
    )
    if cs is None:
        cs = CampaignSettings(tenant_id=tenant_id)
        session.add(cs)
        await session.flush()
    return cs


@router.get("/settings", response_model=SettingsOut)
async def get_settings_blob(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> CampaignSettings:
    return await _get_campaign_settings(session, tenant_id)


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings_blob(
    body: SettingsPatch,
    actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> CampaignSettings:
    cs = await _get_campaign_settings(session, tenant_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cs, field, value)
    await session.commit()
    await session.refresh(cs)
    return cs


# --------------------------------------------------------------------------- #
# /validation-rules — frontend-shaped view over the JSONB rule set
# --------------------------------------------------------------------------- #


async def _get_rule_set(session: SessionDep, tenant_id: uuid.UUID) -> ValidationRuleSet:
    rs = await session.scalar(
        select(ValidationRuleSet).where(ValidationRuleSet.tenant_id == tenant_id)
    )
    if rs is None:
        rs = ValidationRuleSet(tenant_id=tenant_id, rules=default_validation_rules())
        session.add(rs)
        await session.flush()
    return rs


def _rules_to_out(rules: dict) -> ValidationRulesOut:
    """Map the stored JSONB (pipeline keys) to the frontend-facing view."""
    return ValidationRulesOut(
        disposable_domains=list(rules.get("disposable_domains") or []),
        role_based_keywords=list(
            rules.get("role_based_keywords") or rules.get("role_keywords") or DEFAULT_ROLE_KEYWORDS
        ),
        llm_threshold=float(rules.get("llm_threshold", 0.55)),
        catch_all_handling=str(
            rules.get("catch_all_handling") or rules.get("catch_all_policy") or "review"
        ),
        risk_handling=str(rules.get("risk_handling") or rules.get("risk_policy") or "review"),
        unknown_retry_policy=_unknown_to_policy(rules),
    )


def _unknown_to_policy(rules: dict) -> str:
    if rules.get("unknown_retry_policy"):
        return str(rules["unknown_retry_policy"])
    # Pipeline stores unknown_retry as an int retry count; >0 => "retry".
    raw = rules.get("unknown_retry")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (int, float)):
        return "retry" if raw and raw > 0 else "review"
    return "retry"


@router.get("/validation-rules", response_model=ValidationRulesOut)
async def get_validation_rules(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> ValidationRulesOut:
    rs = await _get_rule_set(session, tenant_id)
    return _rules_to_out(rs.rules or {})


@router.patch("/validation-rules", response_model=ValidationRulesOut)
async def patch_validation_rules(
    body: ValidationRulesPatch,
    actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> ValidationRulesOut:
    rs = await _get_rule_set(session, tenant_id)
    rules = dict(rs.rules or {})
    before = _rules_to_out(rules).model_dump(mode="json")
    patch = body.model_dump(exclude_unset=True)

    if "disposable_domains" in patch:
        rules["disposable_domains"] = [
            d.strip().lower() for d in patch["disposable_domains"] if d.strip()
        ]
    if "role_based_keywords" in patch:
        kws = [k.strip().lower() for k in patch["role_based_keywords"] if k.strip()]
        rules["role_based_keywords"] = kws
        rules["role_keywords"] = kws  # pipeline key
    if "llm_threshold" in patch:
        rules["llm_threshold"] = float(patch["llm_threshold"])
    if "catch_all_handling" in patch:
        rules["catch_all_handling"] = patch["catch_all_handling"]
        rules["catch_all_policy"] = patch["catch_all_handling"]  # pipeline key
    if "risk_handling" in patch:
        rules["risk_handling"] = patch["risk_handling"]
        rules["risk_policy"] = patch["risk_handling"]  # pipeline key
    if "unknown_retry_policy" in patch:
        rules["unknown_retry_policy"] = patch["unknown_retry_policy"]
        # pipeline reads unknown_retry as a retry count: "retry" => 1, else 0.
        rules["unknown_retry"] = 1 if patch["unknown_retry_policy"] == "retry" else 0

    rs.rules = rules
    # SQLAlchemy needs the JSONB reassignment flagged as dirty.
    session.add(rs)
    flag_modified(rs, "rules")

    after = _rules_to_out(rules).model_dump(mode="json")
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor.id,
            action="validation_rules.updated",
            entity_type="validation_rule_set",
            entity_id=str(rs.id),
            before_json=before,
            after_json=after,
        )
    )
    await session.commit()
    await session.refresh(rs)
    return _rules_to_out(rs.rules or {})


# --------------------------------------------------------------------------- #
# /settings/env-keys — the repo .env single-source-of-truth key manager
#
# The whole surface is ADMIN-ONLY (WriteActor / "settings:manage"): the list
# exposes non-secret config in the clear and the set-status of every secret,
# reveal returns a plaintext secret, and update rewrites the repo .env. A
# non-admin (e.g. sales_manager) gets 403 on every route here.
#
# Secrets NEVER leak in the list response: a set secret shows only ``****last4``
# in ``masked`` with ``value=None``; the plaintext is only ever returned by the
# dedicated, audited reveal endpoint. Non-secret config carries plaintext in
# ``value`` for direct display/edit.
# --------------------------------------------------------------------------- #


def _env_rows(values: dict[str, str]) -> list[EnvKeyOut]:
    """Render the managed allowlist as list rows from a KEY->value map.

    Order follows :data:`MANAGED_ENV_KEYS`. Secrets are masked (never plaintext);
    non-secrets carry their value in the clear. A blank/absent value is ``unset``.
    """
    rows: list[EnvKeyOut] = []
    for mk in MANAGED_ENV_KEYS:
        raw = values.get(mk.key, "")
        is_set = raw != ""
        rows.append(
            EnvKeyOut(
                key=mk.key,
                label=mk.label,
                group=mk.group,
                is_secret=mk.is_secret,
                is_set=is_set,
                masked=mask_secret(raw) if (mk.is_secret and is_set) else None,
                value=(raw if not mk.is_secret else None),
                source="env" if is_set else "unset",
            )
        )
    return rows


@router.get("/settings/env-keys", response_model=list[EnvKeyOut])
async def list_env_keys(_actor: WriteActor) -> list[EnvKeyOut]:
    """Managed ``.env`` keys, grouped, with secrets masked (admin-only)."""
    values = await run_in_threadpool(read_env)
    return _env_rows(values)


@router.put("/settings/env-keys", response_model=list[EnvKeyOut])
async def update_env_keys(
    body: EnvKeyUpdate,
    actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> list[EnvKeyOut]:
    """Write one or more managed ``.env`` values, hot-reload, return the fresh list.

    Rejects any key outside the managed allowlist (400). Audited: records which
    keys changed (never their values) so the ledger doesn't leak secrets.
    """
    try:
        # Validate every incoming key is managed before touching the file.
        for key in body.values:
            managed_key(key)
    except UnmanagedKeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        refreshed = await run_in_threadpool(write_env_values, body.values)
    except UnmanagedKeyError as exc:  # pragma: no cover - guarded above
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if body.values:
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor.id,
                action="env_keys.updated",
                entity_type="env_file",
                entity_id=".env",
                # Record only WHICH keys changed — never their values.
                before_json=None,
                after_json={"keys": sorted(body.values)},
            )
        )
        await session.commit()

    return _env_rows(refreshed)


@router.post("/settings/env-keys/reveal", response_model=EnvKeyReveal)
async def reveal_env_key(
    body: EnvKeyRevealRequest,
    actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> EnvKeyReveal:
    """Return the full plaintext of one managed key (admin-only, audited).

    Rejects unmanaged keys (400). The value may be an empty string when unset.
    The reveal itself is audited (which key, never the value).
    """
    try:
        managed_key(body.key)
    except UnmanagedKeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    values = await run_in_threadpool(read_env)
    value = values.get(body.key, "")

    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor.id,
            action="env_keys.revealed",
            entity_type="env_file",
            entity_id=body.key,
            before_json=None,
            after_json=None,
        )
    )
    await session.commit()

    return EnvKeyReveal(key=body.key, value=value)
