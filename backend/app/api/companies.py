"""Company endpoints (spec §19).

GET   /companies         list + filters (job_id/source/status/city/text), paginated
GET   /companies/{id}    detail: contacts + CompanySource evidence + hiring signals
PATCH /companies/{id}    edit curated fields
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.deps import SessionDep, TenantId, require
from app.models import Company, CompanySource
from app.schemas.company import CompanyDetail, CompanyOut, CompanyPatch

router = APIRouter(prefix="/companies", tags=["companies"])

ReadActor = Annotated[Company, Depends(require("companies:read"))]
WriteActor = Annotated[Company, Depends(require("companies:write"))]


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    job_id: uuid.UUID | None = None,
    source: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    city: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Company]:
    stmt = select(Company).where(Company.tenant_id == tenant_id)
    if job_id:
        stmt = stmt.where(Company.job_id == job_id)
    if city:
        stmt = stmt.where(Company.city.ilike(f"%{city}%"))
    if status_filter:
        stmt = stmt.where(Company.website_status == status_filter)
    if source:
        stmt = stmt.where(
            Company.id.in_(
                select(CompanySource.company_id).where(CompanySource.source_name == source)
            )
        )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Company.canonical_name.ilike(like),
                Company.domain.ilike(like),
                Company.city.ilike(like),
            )
        )
    stmt = stmt.order_by(Company.created_at).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


@router.get("/{company_id}", response_model=CompanyDetail)
async def get_company(
    company_id: uuid.UUID, _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> Company:
    company = await session.scalar(
        select(Company)
        .where(Company.id == company_id, Company.tenant_id == tenant_id)
        .options(
            selectinload(Company.contacts),
            selectinload(Company.sources),
            selectinload(Company.hiring_signals),
        )
    )
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


@router.patch("/{company_id}", response_model=CompanyOut)
async def patch_company(
    company_id: uuid.UUID,
    body: CompanyPatch,
    _actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> Company:
    company = await session.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    data = body.model_dump(exclude_unset=True)
    for field in ("canonical_name", "website", "phone", "industry", "company_size"):
        if field in data and data[field] is not None:
            setattr(company, field, data[field])
    await session.commit()
    await session.refresh(company)
    return company
