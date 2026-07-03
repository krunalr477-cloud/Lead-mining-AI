"""Data-source compliance endpoints (spec §8 / §17 — Data Source Compliance screen).

GET   /sources                 list the tenant's data-source configs (+ card metadata)
PATCH /sources/{name}          toggle a source's enabled state
POST  /sources/{name}/signoff  admin/legal sign-off for a gated source

Every source known to the adapter registry is returned even if the tenant has no
DataSourceConfig row yet — the card (posture / requires_signoff / access_method /
legal_note) comes from the adapter, so the screen never shows an empty grid.
Enabling a gated source that is not signed off is refused; sign-off is recorded
in the audit log with the admin's identity + timestamp.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.adapters.registry import get_registry
from app.constants import SourceName
from app.db import utcnow
from app.deps import CurrentUser, SessionDep, TenantId, require
from app.models import AuditLog, DataSourceConfig, User
from app.schemas.settings import DataSourceOut, SourcePatch

router = APIRouter(prefix="/sources", tags=["sources"])

ReadActor = Annotated[User, Depends(require("dashboard:read"))]
WriteActor = Annotated[User, Depends(require("settings:manage"))]

# Human-facing labels for the source cards.
_DISPLAY_NAMES: dict[str, str] = {
    SourceName.GOOGLE_MAPS: "Google Maps",
    SourceName.COMPANY_WEBSITES: "Company Websites",
    SourceName.DIRECTORIES: "Business Directories",
    SourceName.YELLOW_PAGES: "Yellow Pages",
    SourceName.CLUTCH: "Clutch",
    SourceName.FACEBOOK_SIGNALS: "Facebook Signals",
    SourceName.SERP_JOBS: "SERP / Job Signals",
    SourceName.INDEED: "Indeed",
    SourceName.LINKEDIN: "LinkedIn",
}


def _card_for(name: SourceName):
    return get_registry().adapter_card(name)


def _to_out(name: SourceName, cfg: DataSourceConfig | None) -> DataSourceOut:
    card = _card_for(name)
    signed_off = cfg is not None and cfg.signoff_at is not None
    requires_signoff = cfg.requires_signoff if cfg is not None else bool(card.requires_signoff)
    rate = cfg.rate_limit_per_minute if cfg is not None else None
    return DataSourceOut(
        name=name.value,
        display_name=_DISPLAY_NAMES.get(name, name.value),
        source_type=card.source_type,
        access_method=(cfg.access_method if cfg is not None else card.access_method.value),
        posture=(cfg.compliance_posture if cfg is not None else card.posture.value),
        enabled=bool(cfg.enabled) if cfg is not None else False,
        legal_note=(cfg.legal_note if cfg is not None else card.legal_note) or None,
        requires_signoff=requires_signoff,
        signed_off=signed_off,
        signed_off_by=str(cfg.signoff_user_id) if signed_off and cfg else None,
        signed_off_at=cfg.signoff_at if cfg is not None else None,
        last_success_at=cfg.last_success_at if cfg is not None else None,
        last_failure_at=cfg.last_failure_at if cfg is not None else None,
        rate_limit=f"{rate}/min" if rate else None,
    )


async def _configs(session: SessionDep, tenant_id: uuid.UUID) -> dict[str, DataSourceConfig]:
    rows = await session.scalars(
        select(DataSourceConfig).where(DataSourceConfig.tenant_id == tenant_id)
    )
    return {c.source_name: c for c in rows}


@router.get("", response_model=list[DataSourceOut])
async def list_sources(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> list[DataSourceOut]:
    configs = await _configs(session, tenant_id)
    return [_to_out(name, configs.get(name.value)) for name in get_registry().source_names()]


async def _get_config(
    session: SessionDep, tenant_id: uuid.UUID, name: SourceName
) -> DataSourceConfig:
    cfg = await session.scalar(
        select(DataSourceConfig).where(
            DataSourceConfig.tenant_id == tenant_id,
            DataSourceConfig.source_name == name.value,
        )
    )
    if cfg is None:
        # Materialize a row from the card so the source becomes configurable.
        card = _card_for(name)
        cfg = DataSourceConfig(
            tenant_id=tenant_id,
            source_name=name.value,
            enabled=False,
            compliance_posture=card.posture.value,
            access_method=card.access_method.value,
            legal_note=card.legal_note or None,
            requires_signoff=bool(card.requires_signoff),
        )
        session.add(cfg)
        await session.flush()
    return cfg


def _resolve_name(name: str) -> SourceName:
    try:
        return SourceName(name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {name}"
        ) from exc


@router.patch("/{name}", response_model=DataSourceOut)
async def patch_source(
    name: str,
    body: SourcePatch,
    actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> DataSourceOut:
    source = _resolve_name(name)
    cfg = await _get_config(session, tenant_id, source)
    before = {"enabled": cfg.enabled}
    if body.enabled is not None:
        if body.enabled and cfg.requires_signoff and cfg.signoff_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This source requires compliance sign-off before it can be enabled.",
            )
        cfg.enabled = body.enabled
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor.id,
            action="source.updated",
            entity_type="data_source_config",
            entity_id=source.value,
            before_json=before,
            after_json={"enabled": cfg.enabled},
        )
    )
    await session.commit()
    await session.refresh(cfg)
    return _to_out(source, cfg)


@router.post("/{name}/signoff", response_model=DataSourceOut)
async def signoff_source(
    name: str,
    actor: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
    _perm: WriteActor,
) -> DataSourceOut:
    source = _resolve_name(name)
    cfg = await _get_config(session, tenant_id, source)
    cfg.signoff_user_id = actor.id
    cfg.signoff_at = utcnow()
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor.id,
            action="source.signoff",
            entity_type="data_source_config",
            entity_id=source.value,
            before_json=None,
            after_json={
                "signed_off_by": str(actor.id),
                "signed_off_at": cfg.signoff_at.isoformat(),
            },
        )
    )
    await session.commit()
    await session.refresh(cfg)
    return _to_out(source, cfg)
