"""Email-template CRUD (spec §13).

GET    /templates          list
POST   /templates          create
GET    /templates/{id}     one
PATCH  /templates/{id}     update
DELETE /templates/{id}     delete
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.deps import SessionDep, TenantId, require
from app.models import EmailTemplate, Tenant
from app.outreach.renderer import used_variables
from app.schemas.campaign import TemplateCreate, TemplateOut, TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])

ReadActor = Annotated[Tenant, Depends(require("templates:read"))]
WriteActor = Annotated[Tenant, Depends(require("templates:write"))]


def _validate_template(subject: str, body: str) -> None:
    """Reject templates that reference unknown variables (fail fast at save)."""
    from app.constants import TEMPLATE_VARIABLES

    allowed = set(TEMPLATE_VARIABLES)
    unknown = sorted(
        {v for v in used_variables(subject) + used_variables(body) if v not in allowed}
    )
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown template variable(s): {', '.join(unknown)}",
        )


async def _get(session: SessionDep, tenant_id: uuid.UUID, template_id: uuid.UUID) -> EmailTemplate:
    tpl = await session.get(EmailTemplate, template_id)
    if tpl is None or tpl.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return tpl


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EmailTemplate]:
    stmt = (
        select(EmailTemplate)
        .where(EmailTemplate.tenant_id == tenant_id)
        .order_by(EmailTemplate.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(await session.scalars(stmt))


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> EmailTemplate:
    _validate_template(body.subject, body.body)
    tpl = EmailTemplate(
        tenant_id=tenant_id,
        name=body.name,
        subject=body.subject,
        body=body.body,
        created_by=actor.id,
    )
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return tpl


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: uuid.UUID, _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> EmailTemplate:
    return await _get(session, tenant_id, template_id)


@router.patch("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    _actor: WriteActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> EmailTemplate:
    tpl = await _get(session, tenant_id, template_id)
    subject = body.subject if body.subject is not None else tpl.subject
    template_body = body.body if body.body is not None else tpl.body
    _validate_template(subject, template_body)
    if body.name is not None:
        tpl.name = body.name
    tpl.subject = subject
    tpl.body = template_body
    await session.commit()
    await session.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID, _actor: WriteActor, tenant_id: TenantId, session: SessionDep
) -> None:
    tpl = await _get(session, tenant_id, template_id)
    await session.delete(tpl)
    await session.commit()
