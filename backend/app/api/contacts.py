"""Contact endpoints (spec §19).

GET   /contacts             list + filters, paginated
GET   /contacts/{id}        detail: contact + validation history
PATCH /contacts/{id}        edit owner/notes/next_action (-> Contacts sheet upsert);
                            sales_executive may patch only contacts they own
POST  /contacts/{id}/verify re-run validation for the contact's emails
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.constants import Role
from app.deps import CurrentUser, SessionDep, TenantId, require
from app.models import Contact, EmailCandidate
from app.schemas.contact import ContactDetail, ContactOut, ValidationCheckOut

router = APIRouter(prefix="/contacts", tags=["contacts"])

ReadActor = Annotated[Contact, Depends(require("contacts:read"))]


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    job_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    role_category: str | None = None,
    email_status: str | None = None,
    sales_ready: bool | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Contact]:
    stmt = select(Contact).where(Contact.tenant_id == tenant_id)
    if job_id:
        stmt = stmt.where(Contact.job_id == job_id)
    if company_id:
        stmt = stmt.where(Contact.company_id == company_id)
    if role_category:
        stmt = stmt.where(Contact.role_category.ilike(f"%{role_category}%"))
    if email_status:
        stmt = stmt.where(Contact.final_email_status == email_status)
    if sales_ready is not None:
        stmt = stmt.where(Contact.sales_ready.is_(sales_ready))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Contact.full_name.ilike(like),
                Contact.email.ilike(like),
                Contact.designation.ilike(like),
            )
        )
    stmt = stmt.order_by(Contact.created_at).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


@router.get("/{contact_id}", response_model=ContactDetail)
async def get_contact(
    contact_id: uuid.UUID, _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> Contact:
    contact = await session.scalar(
        select(Contact)
        .where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
        .options(selectinload(Contact.validation_checks))
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


class _ContactPatch(ContactOut):
    pass


@router.patch("/{contact_id}", response_model=ContactOut)
async def patch_contact(
    contact_id: uuid.UUID,
    body: dict,
    user: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
) -> Contact:
    """Edit sales-owned fields. Enforces contacts:write (managers/admin) OR
    contacts:write_own (executives, only their own contacts)."""
    contact = await session.get(Contact, contact_id)
    if contact is None or contact.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    role = _role_of(user)
    from app.security.rbac import has_permission

    can_write_all = role is not None and has_permission(role, "contacts:write")
    can_write_own = role is not None and has_permission(role, "contacts:write_own")
    if not (can_write_all or can_write_own):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: contacts:write"
        )
    if not can_write_all and can_write_own and contact.owner_user_id not in (None, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sales executives may only edit contacts they own",
        )

    # Apply the sales-editable fields.
    if "owner_user_id" in body:
        raw = body["owner_user_id"]
        contact.owner_user_id = uuid.UUID(str(raw)) if raw else None
    if "notes" in body:
        contact.notes = body["notes"]
    # next_action has no dedicated column yet; fold it into notes metadata is
    # avoided — it round-trips via the sheet's editable next_action column.

    # Mirror the contact row to the Contacts sheet tab.
    await run_in_threadpool(_enqueue_contact_sheet, tenant_id, contact.id)

    await session.commit()
    await session.refresh(contact)
    return contact


@router.post("/{contact_id}/verify", response_model=list[ValidationCheckOut])
async def verify_contact(
    contact_id: uuid.UUID,
    tenant_id: TenantId,
    session: SessionDep,
    _actor: Annotated[Contact, Depends(require("validation:run"))],
) -> list:
    contact = await session.get(Contact, contact_id)
    if contact is None or contact.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    candidate_ids = list(
        await session.scalars(
            select(EmailCandidate.id).where(EmailCandidate.contact_id == contact_id)
        )
    )
    if not candidate_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No email candidates to verify"
        )

    return await run_in_threadpool(
        _revalidate_candidates, tenant_id, [str(c) for c in candidate_ids]
    )


# --------------------------------------------------------------------------- #
# Sync helpers (run in a threadpool — sync Session)
# --------------------------------------------------------------------------- #


def _role_of(user) -> Role | None:
    try:
        return Role(user.role)
    except ValueError:
        return None


def _enqueue_contact_sheet(tenant_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    from app.db import sync_session_factory
    from app.pipeline.stages import sync_contact_row

    with sync_session_factory() as session:
        sync_contact_row(session, tenant_id, contact_id)
        session.commit()


def _revalidate_candidates(tenant_id: uuid.UUID, candidate_ids: list[str]) -> list:
    from app.db import sync_session_factory
    from app.models import MiningJob
    from app.pipeline import stages
    from app.workers.rate_limit import get_redis

    out = []
    with sync_session_factory() as session:
        redis_client = get_redis()
        for cid in candidate_ids:
            cand = session.get(EmailCandidate, uuid.UUID(cid))
            if cand is None:
                continue
            contact = session.get(Contact, cand.contact_id)
            job = session.get(MiningJob, contact.job_id) if contact and contact.job_id else None
            if job is None:
                continue
            check = stages.run_validation_for_candidate(session, redis_client, job, cand)
            stages._enqueue(session, tenant_id, "Email_Validation", str(check.id))
            stages.sync_contact_row(session, tenant_id, cand.contact_id)
            stages.recompute_sales_ready_for_job(session, job)
            out.append(ValidationCheckOut.model_validate(check))
        session.commit()
    return out
