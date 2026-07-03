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

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

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
    SettingsOut,
    SettingsPatch,
    ValidationRulesOut,
    ValidationRulesPatch,
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
