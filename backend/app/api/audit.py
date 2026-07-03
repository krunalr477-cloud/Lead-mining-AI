"""Audit-log endpoints (spec §17 — Audit screen).

GET /audit  the tenant's mutation ledger (actor / action / entity / before-after)

Read-only, admin/manager gated (``audit:read``). Supports substring search over
action/entity plus exact action / entity_type filters and pagination.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.deps import SessionDep, TenantId, require
from app.models import AuditLog, User
from app.schemas.settings import AuditEntryOut

router = APIRouter(prefix="/audit", tags=["audit"])

ReadActor = Annotated[User, Depends(require("audit:read"))]


@router.get("", response_model=list[AuditEntryOut])
async def list_audit(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    q: Annotated[str | None, Query(description="Substring over action/entity")] = None,
    action: str | None = None,
    entity_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEntryOut]:
    stmt = select(AuditLog, User.name).where(AuditLog.tenant_id == tenant_id)
    stmt = stmt.outerjoin(User, User.id == AuditLog.actor_user_id)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(AuditLog.action).like(pattern),
                func.lower(AuditLog.entity_type).like(pattern),
                func.lower(func.coalesce(AuditLog.entity_id, "")).like(pattern),
            )
        )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    return [
        AuditEntryOut(
            id=log.id,
            actor=str(log.actor_user_id) if log.actor_user_id else None,
            actor_name=actor_name,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            before=log.before_json,
            after=log.after_json,
            created_at=log.created_at,
        )
        for log, actor_name in rows
    ]
