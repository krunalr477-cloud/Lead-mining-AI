"""Campaign endpoints (spec §13).

POST   /campaigns               create a draft campaign
GET    /campaigns               list a tenant's campaigns
GET    /campaigns/{id}          one campaign + stats + eligibility summary
GET    /campaigns/{id}/preview  render subject/body for a contact (variable menu)
POST   /campaigns/{id}/test     send a single test email
POST   /campaigns/{id}/launch   re-check eligibility, schedule, start sending
POST   /campaigns/{id}/pause    pause an active campaign
POST   /campaigns/{id}/resume   resume a paused campaign
POST   /campaigns/{id}/cancel   cancel a campaign

Launch re-derives the recipient list and re-checks per-recipient eligibility
(spec §25 HARD rule): it refuses to launch when no VERIFIED, non-suppressed
recipient remains.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.constants import TEMPLATE_VARIABLES, CampaignStatus, MessageStatus
from app.db import sync_session_factory, utcnow
from app.deps import SessionDep, TenantId, require
from app.models import Campaign, Contact, EmailMessage, EmailTemplate, Tenant
from app.schemas.campaign import (
    CampaignCreate,
    CampaignDetail,
    CampaignOut,
    CampaignStats,
    EligibilitySummary,
    TestEmailRequest,
)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

ReadActor = Annotated[Tenant, Depends(require("campaigns:read"))]
CreateActor = Annotated[Tenant, Depends(require("campaigns:create"))]
ControlActor = Annotated[Tenant, Depends(require("campaigns:control"))]


async def _get_campaign(
    session: SessionDep, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreate,
    actor: CreateActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> Campaign:
    subject = body.subject_template
    template_body = body.body_template
    if body.template_id is not None:
        template = await session.get(EmailTemplate, body.template_id)
        if template is None or template.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        subject = body.subject_template or template.subject
        template_body = body.body_template or template.body

    campaign = Campaign(
        tenant_id=tenant_id,
        created_by=actor.id,
        job_id=body.job_id,
        template_id=body.template_id,
        name=body.name,
        subject_template=subject,
        body_template=template_body,
        from_account=body.from_account,
        rate_limit_per_hour=body.rate_limit_per_hour,
        rate_limit_per_day=body.rate_limit_per_day,
        tracking_enabled=body.tracking_enabled,
        status=CampaignStatus.DRAFT.value,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Campaign]:
    stmt = (
        select(Campaign)
        .where(Campaign.tenant_id == tenant_id)
        .order_by(Campaign.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(await session.scalars(stmt))


async def _stats(session: SessionDep, campaign_id: uuid.UUID) -> CampaignStats:
    rows = await session.execute(
        select(EmailMessage.status, func.count())
        .where(EmailMessage.campaign_id == campaign_id)
        .group_by(EmailMessage.status)
    )
    by_status = {status_: count for status_, count in rows.all()}
    total = sum(by_status.values())
    # "sent" counts anything that reached the wire (Sent + downstream states).
    downstream = {
        MessageStatus.SENT.value,
        MessageStatus.DELIVERED.value,
        MessageStatus.OPENED.value,
        MessageStatus.CLICKED.value,
        MessageStatus.REPLIED.value,
    }
    sent = sum(c for s, c in by_status.items() if s in downstream)
    return CampaignStats(
        recipient_count=total,
        sent=sent,
        delivered=by_status.get(MessageStatus.DELIVERED.value, 0)
        + by_status.get(MessageStatus.OPENED.value, 0)
        + by_status.get(MessageStatus.CLICKED.value, 0)
        + by_status.get(MessageStatus.REPLIED.value, 0),
        opened=by_status.get(MessageStatus.OPENED.value, 0),
        clicked=by_status.get(MessageStatus.CLICKED.value, 0),
        replied=by_status.get(MessageStatus.REPLIED.value, 0),
        bounced=by_status.get(MessageStatus.HARD_BOUNCE.value, 0)
        + by_status.get(MessageStatus.SOFT_BOUNCE.value, 0)
        + by_status.get(MessageStatus.BLOCKED.value, 0)
        + by_status.get(MessageStatus.SPAM_COMPLAINT.value, 0),
        queued=by_status.get(MessageStatus.QUEUED.value, 0),
    )


@router.get("/variables")
async def list_variables(_actor: ReadActor) -> dict:
    """Template-variable menu for the campaign builder."""
    return {"variables": list(TEMPLATE_VARIABLES)}


@router.get("/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(
    campaign_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> CampaignDetail:
    campaign = await _get_campaign(session, tenant_id, campaign_id)
    stats = await _stats(session, campaign_id)
    detail = CampaignDetail(
        **CampaignOut.model_validate(campaign).model_dump(),
        stats=stats,
    )
    return detail


@router.get("/{campaign_id}/eligibility", response_model=EligibilitySummary)
async def eligibility(
    campaign_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> EligibilitySummary:
    await _get_campaign(session, tenant_id, campaign_id)

    def _plan(cid: uuid.UUID) -> EligibilitySummary:
        with sync_session_factory() as s:
            from app.outreach.scheduler import plan_recipients

            campaign = s.get(Campaign, cid)
            decisions = plan_recipients(s, campaign)
            eligible = sum(1 for d in decisions if d.eligible)
            rejected: dict[str, int] = {}
            for d in decisions:
                if d.reason:
                    rejected[d.reason] = rejected.get(d.reason, 0) + 1
            return EligibilitySummary(
                candidates=len(decisions), eligible=eligible, rejected=rejected
            )

    return await run_in_threadpool(_plan, campaign_id)


@router.post("/{campaign_id}/preview")
async def preview(
    campaign_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    await _get_campaign(session, tenant_id, campaign_id)
    if contact_id is not None:
        contact = await session.get(Contact, contact_id)
        if contact is None or contact.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    def _render(cid: uuid.UUID, ctid: uuid.UUID | None) -> dict:
        with sync_session_factory() as s:
            from app.models import Company
            from app.outreach.renderer import TemplateRenderError, build_context, render
            from app.outreach.scheduler import build_recipient_facts

            c = s.get(Campaign, cid)
            ct = s.get(Contact, ctid) if ctid else None
            if ct is not None:
                comp = s.get(Company, ct.company_id) if ct.company_id else None
                ctx = build_context(build_recipient_facts(ct, comp, None))
            else:
                ctx = {v: f"[{v}]" for v in TEMPLATE_VARIABLES}
            try:
                return {
                    "subject": render(c.subject_template, ctx),
                    "body": render(c.body_template, ctx),
                    "ok": True,
                }
            except TemplateRenderError as exc:
                return {"ok": False, "error": str(exc)}

    return await run_in_threadpool(_render, campaign_id, contact_id)


@router.post("/{campaign_id}/test")
async def test_email(
    campaign_id: uuid.UUID,
    body: TestEmailRequest,
    _actor: ControlActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> dict:
    await _get_campaign(session, tenant_id, campaign_id)

    def _send(cid: uuid.UUID, to: str, ctid: uuid.UUID | None) -> dict:
        with sync_session_factory() as s:
            from app.adapters.google.gmail_client import get_gmail_client
            from app.models import Company
            from app.outreach.renderer import build_context, render
            from app.outreach.scheduler import build_recipient_facts
            from app.outreach.sender import DEFAULT_UNSUB_TEXT, append_unsubscribe_footer

            c = s.get(Campaign, cid)
            ct = s.get(Contact, ctid) if ctid else None
            if ct is not None:
                comp = s.get(Company, ct.company_id) if ct.company_id else None
                ctx = build_context(build_recipient_facts(ct, comp, None))
            else:
                ctx = {v: f"[{v}]" for v in TEMPLATE_VARIABLES}
            subject = render(c.subject_template, ctx)
            body_text = append_unsubscribe_footer(render(c.body_template, ctx), DEFAULT_UNSUB_TEXT)
            client = get_gmail_client(c.tenant_id, s, c.from_account)
            result = client.send(
                to=to,
                subject=f"[TEST] {subject}",
                body=body_text,
                headers={"X-LeadMine-Test": "1"},
            )
            s.commit()
            return {"sent": True, "gmail_message_id": result.id}

    return await run_in_threadpool(_send, campaign_id, str(body.to), body.contact_id)


@router.post("/{campaign_id}/launch", response_model=CampaignDetail)
async def launch(
    campaign_id: uuid.UUID,
    _actor: ControlActor,
    tenant_id: TenantId,
    session: SessionDep,
    inline: Annotated[bool, Query(description="Send synchronously (demo)")] = False,
) -> CampaignDetail:
    campaign = await _get_campaign(session, tenant_id, campaign_id)
    if campaign.status in (CampaignStatus.SENDING.value, CampaignStatus.COMPLETED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Campaign already {campaign.status}"
        )

    # Re-check eligibility + schedule in a sync worker session (spec §25 guard).
    def _schedule(cid: uuid.UUID) -> dict:
        with sync_session_factory() as s:
            from app.outreach.scheduler import schedule_campaign

            c = s.get(Campaign, cid)
            summary = schedule_campaign(s, c)
            if summary["recipient_count"] == 0:
                s.rollback()
                return {
                    "recipient_count": 0,
                    "rejected": summary.get("rejected", {}),
                    "candidates": summary.get("candidates", 0),
                }
            c.status = CampaignStatus.SENDING.value
            c.launched_at = c.launched_at or utcnow()
            from app.outreach.suppression import sync_campaign_side_effects

            sync_campaign_side_effects(s, c.tenant_id, c.id)
            s.commit()
            return summary

    summary = await run_in_threadpool(_schedule, campaign_id)
    if summary["recipient_count"] == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "No verified, non-suppressed recipients. Refusing to launch.",
                "rejected": summary.get("rejected", {}),
                "candidates": summary.get("candidates", 0),
            },
        )

    if inline:
        # Demo: dispatch + send every due message synchronously.
        def _dispatch(cid: uuid.UUID) -> None:
            with sync_session_factory() as s:
                from app.constants import MessageStatus as _MS
                from app.outreach.sender import send_email_message
                from app.workers.tasks.campaign import _maybe_complete

                c = s.get(Campaign, cid)
                msgs = list(
                    s.scalars(
                        select(EmailMessage).where(
                            EmailMessage.campaign_id == cid,
                            EmailMessage.status == _MS.QUEUED.value,
                        )
                    )
                )
                for m in msgs:
                    send_email_message(s, m, enforce_rate_limit=False)
                _maybe_complete(s, c)
                s.commit()

        await run_in_threadpool(_dispatch, campaign_id)
    else:
        from app.workers.tasks.campaign import dispatch_due_messages

        dispatch_due_messages.delay(str(campaign_id))

    await session.refresh(campaign)
    stats = await _stats(session, campaign_id)
    return CampaignDetail(
        **CampaignOut.model_validate(campaign).model_dump(),
        stats=stats,
        estimated_hours=summary.get("estimated_hours"),
    )


async def _transition(
    session: SessionDep,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    allowed_from: set[str],
    to: str,
) -> Campaign:
    campaign = await _get_campaign(session, tenant_id, campaign_id)
    if campaign.status not in allowed_from:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot move campaign from {campaign.status} to {to}",
        )
    campaign.status = to
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
async def pause(
    campaign_id: uuid.UUID, _actor: ControlActor, tenant_id: TenantId, session: SessionDep
) -> Campaign:
    return await _transition(
        session,
        tenant_id,
        campaign_id,
        allowed_from={
            CampaignStatus.SENDING.value,
            CampaignStatus.QUEUED.value,
            CampaignStatus.SCHEDULED.value,
        },
        to=CampaignStatus.PAUSED.value,
    )


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
async def resume(
    campaign_id: uuid.UUID, _actor: ControlActor, tenant_id: TenantId, session: SessionDep
) -> Campaign:
    campaign = await _transition(
        session,
        tenant_id,
        campaign_id,
        allowed_from={CampaignStatus.PAUSED.value},
        to=CampaignStatus.SENDING.value,
    )
    from app.workers.tasks.campaign import dispatch_due_messages

    dispatch_due_messages.delay(str(campaign_id))
    return campaign


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel(
    campaign_id: uuid.UUID, _actor: ControlActor, tenant_id: TenantId, session: SessionDep
) -> Campaign:
    # Cancelling flips the campaign out of any active send state; ``send_message``
    # refuses to fire QUEUED rows once the campaign is no longer sending, so the
    # remaining queue is effectively frozen without touching the rows.
    return await _transition(
        session,
        tenant_id,
        campaign_id,
        allowed_from={
            CampaignStatus.DRAFT.value,
            CampaignStatus.SCHEDULED.value,
            CampaignStatus.QUEUED.value,
            CampaignStatus.SENDING.value,
            CampaignStatus.PAUSED.value,
        },
        to=CampaignStatus.CANCELLED.value,
    )
