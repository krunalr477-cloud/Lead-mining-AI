"""Bounce endpoints (spec §14).

GET  /bounces          list bounce events for the tenant (most recent first)
POST /bounces/poll     trigger an on-demand bounce+reply poll
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.deps import SessionDep, TenantId, require
from app.models import BounceEvent, Campaign, EmailMessage, Tenant
from app.schemas.campaign import BounceOut

router = APIRouter(prefix="/bounces", tags=["bounces"])

ReadActor = Annotated[Tenant, Depends(require("bounces:read"))]
PollActor = Annotated[Tenant, Depends(require("campaigns:control"))]


@router.get("", response_model=list[BounceOut])
async def list_bounces(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    campaign_id: uuid.UUID | None = None,
    bounce_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BounceEvent]:
    stmt = (
        select(BounceEvent)
        .join(EmailMessage, BounceEvent.email_message_id == EmailMessage.id)
        .join(Campaign, EmailMessage.campaign_id == Campaign.id)
        .where(Campaign.tenant_id == tenant_id)
    )
    if campaign_id is not None:
        stmt = stmt.where(Campaign.id == campaign_id)
    if bounce_type is not None:
        stmt = stmt.where(BounceEvent.bounce_type == bounce_type)
    stmt = stmt.order_by(BounceEvent.detected_at.desc()).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


@router.post("/poll", status_code=status.HTTP_202_ACCEPTED)
async def poll_now(
    _actor: PollActor,
    tenant_id: TenantId,
    inline: Annotated[bool, Query(description="Poll synchronously (demo)")] = False,
) -> dict:
    if inline:

        def _run(tid: uuid.UUID) -> dict:
            from app.workers.tasks.bounce import poll_bounces, poll_replies

            bounces = poll_bounces.apply(kwargs={"tenant_id": str(tid)}).get()
            replies = poll_replies.apply(kwargs={"tenant_id": str(tid)}).get()
            return {"bounces": bounces, "replies": replies}

        return await run_in_threadpool(_run, tenant_id)

    from app.workers.tasks.bounce import poll_bounces, poll_replies

    poll_bounces.delay(str(tenant_id))
    poll_replies.delay(str(tenant_id))
    return {"status": "queued"}
