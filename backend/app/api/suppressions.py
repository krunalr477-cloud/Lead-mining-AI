"""Suppression-list endpoints (spec §14 / §16 Compliance).

GET    /suppressions          list suppressed emails/domains
POST   /suppressions          add a manual suppression (email or domain)
DELETE /suppressions/{id}     remove a suppression (unsuppress)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.deps import SessionDep, TenantId, require
from app.models import Suppression, Tenant
from app.schemas.campaign import SuppressionCreate, SuppressionOut

router = APIRouter(prefix="/suppressions", tags=["suppressions"])

ReadActor = Annotated[Tenant, Depends(require("suppressions:read"))]
WriteActor = Annotated[Tenant, Depends(require("suppressions:write"))]


@router.get("", response_model=list[SuppressionOut])
async def list_suppressions(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    q: str | None = Query(default=None, description="Filter by email/domain substring"),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Suppression]:
    stmt = select(Suppression).where(Suppression.tenant_id == tenant_id)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Suppression.email).like(pattern),
                func.lower(Suppression.domain).like(pattern),
            )
        )
    stmt = stmt.order_by(Suppression.created_at.desc()).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


@router.post("", response_model=SuppressionOut, status_code=status.HTTP_201_CREATED)
async def create_suppression(
    body: SuppressionCreate,
    _actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> Suppression:
    email = (body.email or "").strip() or None
    domain = (body.domain or "").strip() or None
    if not email and not domain:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide an email or a domain to suppress.",
        )
    # Idempotent: return the existing suppression if this address/domain is set.
    existing = None
    if email:
        existing = await session.scalar(
            select(Suppression).where(
                Suppression.tenant_id == tenant_id,
                func.lower(Suppression.email) == email.lower(),
            )
        )
    elif domain:
        existing = await session.scalar(
            select(Suppression).where(
                Suppression.tenant_id == tenant_id,
                func.lower(Suppression.domain) == domain.lower(),
            )
        )
    if existing is not None:
        return existing

    supp = Suppression(
        tenant_id=tenant_id,
        email=email,
        domain=domain,
        reason=body.reason or "Manually suppressed",
        source="manual",
        permanent=body.permanent,
    )
    session.add(supp)
    await session.commit()
    await session.refresh(supp)
    return supp


@router.delete("/{suppression_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suppression(
    suppression_id: uuid.UUID, _actor: WriteActor, tenant_id: TenantId, session: SessionDep
) -> None:
    supp = await session.get(Suppression, suppression_id)
    if supp is None or supp.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suppression not found")
    await session.delete(supp)
    await session.commit()
