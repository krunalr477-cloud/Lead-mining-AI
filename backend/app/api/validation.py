"""Validation endpoints (spec §19).

POST /validation/run              revalidate selected contact/email ids
GET  /validation/{job_id}         stage-column rows for a job (the Validation Pipeline table)
GET  /validation/{contact_id}/history   validation history for one contact
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.deps import SessionDep, TenantId, require
from app.models import Contact, EmailCandidate, ValidationCheck
from app.schemas.contact import ValidationCheckOut, ValidationRunRequest

router = APIRouter(prefix="/validation", tags=["validation"])

ReadActor = Annotated[Contact, Depends(require("validation:read"))]
RunActor = Annotated[Contact, Depends(require("validation:run"))]


@router.post("/run", response_model=list[ValidationCheckOut])
async def run_validation(
    body: ValidationRunRequest,
    _actor: RunActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> list:
    candidate_ids: set[uuid.UUID] = set(body.email_candidate_ids)
    if body.contact_ids:
        rows = await session.scalars(
            select(EmailCandidate.id)
            .join(Contact, EmailCandidate.contact_id == Contact.id)
            .where(
                Contact.tenant_id == tenant_id,
                EmailCandidate.contact_id.in_(body.contact_ids),
            )
        )
        candidate_ids.update(rows)
    if not candidate_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No email candidates resolved"
        )
    from app.api.contacts import _revalidate_candidates

    return await run_in_threadpool(
        _revalidate_candidates, tenant_id, [str(c) for c in candidate_ids]
    )


@router.get("/{job_id}", response_model=list[ValidationCheckOut])
async def validation_for_job(
    job_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ValidationCheck]:
    stmt = (
        select(ValidationCheck)
        .join(Contact, ValidationCheck.contact_id == Contact.id)
        .where(Contact.tenant_id == tenant_id, Contact.job_id == job_id)
        .order_by(ValidationCheck.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(await session.scalars(stmt))


@router.get("/{contact_id}/history", response_model=list[ValidationCheckOut])
async def validation_history(
    contact_id: uuid.UUID, _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> list[ValidationCheck]:
    contact = await session.get(Contact, contact_id)
    if contact is None or contact.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    stmt = (
        select(ValidationCheck)
        .where(ValidationCheck.contact_id == contact_id)
        .order_by(ValidationCheck.created_at.desc())
    )
    return list(await session.scalars(stmt))
