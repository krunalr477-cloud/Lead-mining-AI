"""campaign_jobs queue — schedule, dispatch, and send campaign messages (spec §13).

- ``schedule_campaign(campaign_id)`` — re-check per-recipient eligibility, build
  QUEUED EmailMessage rows, flip the campaign to SENDING/SCHEDULED.
- ``dispatch_due_messages()`` — beat every 1 minute: find QUEUED messages whose
  ``scheduled_at`` has arrived and enqueue a ``send_message`` per message,
  respecting the campaign's send state.
- ``send_message(email_message_id)`` — send one message via Gmail, persist ids.
- ``classify_deliveries()`` — beat: Sent messages with no DSN after the delay
  window flip to Delivered.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.constants import CampaignStatus, MessageStatus
from app.db import utcnow
from app.models import Campaign, EmailMessage
from app.outreach.scheduler import schedule_campaign as _plan_schedule
from app.outreach.sender import send_email_message
from app.outreach.suppression import sync_campaign_side_effects
from app.workers.celery_app import PermanentError, app
from app.workers.tasks._base import worker_session

__all__ = [
    "classify_deliveries",
    "dispatch_due_messages",
    "schedule_campaign",
    "send_message",
]

# Delivery classification window (spec §14: 3-6h). We use the low end (3h) as the
# default; a message Sent longer ago than this with no bounce is Delivered.
DELIVERY_DELAY_HOURS = 3

_ACTIVE_SEND_STATES = {
    CampaignStatus.SENDING.value,
    CampaignStatus.QUEUED.value,
    CampaignStatus.SCHEDULED.value,
}


@app.task(name="app.workers.tasks.campaign.schedule_campaign", bind=True)
def schedule_campaign(self, campaign_id: str) -> dict:
    cid = uuid.UUID(str(campaign_id))
    with worker_session() as session:
        campaign = session.get(Campaign, cid)
        if campaign is None:
            return {"error": "campaign not found"}
        summary = _plan_schedule(session, campaign)
        campaign.status = CampaignStatus.SENDING.value
        campaign.launched_at = campaign.launched_at or utcnow()
        sync_campaign_side_effects(session, campaign.tenant_id, campaign.id)
    return {"campaign_id": str(cid), **summary}


@app.task(name="app.workers.tasks.campaign.dispatch_due_messages", bind=True)
def dispatch_due_messages(self, campaign_id: str | None = None) -> dict:
    """Enqueue a send for every due QUEUED message (beat: every 1 minute)."""
    now = utcnow()
    dispatched = 0
    with worker_session() as session:
        stmt = (
            select(EmailMessage.id)
            .join(Campaign, EmailMessage.campaign_id == Campaign.id)
            .where(
                EmailMessage.status == MessageStatus.QUEUED.value,
                EmailMessage.scheduled_at.is_not(None),
                EmailMessage.scheduled_at <= now,
                Campaign.status.in_(list(_ACTIVE_SEND_STATES)),
            )
        )
        if campaign_id is not None:
            stmt = stmt.where(EmailMessage.campaign_id == uuid.UUID(str(campaign_id)))
        ids = list(session.scalars(stmt))
    for mid in ids:
        send_message.delay(str(mid))
        dispatched += 1
    return {"dispatched": dispatched}


@app.task(name="app.workers.tasks.campaign.send_message", bind=True)
def send_message(self, email_message_id: str) -> dict:
    mid = uuid.UUID(str(email_message_id))
    with worker_session() as session:
        message = session.get(EmailMessage, mid)
        if message is None:
            return {"error": "message not found"}
        if message.status != MessageStatus.QUEUED.value:
            return {"skipped": message.status}
        campaign = session.get(Campaign, message.campaign_id)
        if campaign is None or campaign.status not in _ACTIVE_SEND_STATES:
            return {"skipped": "campaign not sending"}
        try:
            result = send_email_message(session, message)
        except PermanentError as exc:
            # invalid_grant paused the campaign inside the sender; surface it.
            return {"error": str(exc), "campaign_paused": True}
        # Enqueue sheet upserts for the state change.
        from app.pipeline import stages

        stages._enqueue(session, campaign.tenant_id, "Outreach_Queue", str(message.id))
        sync_campaign_side_effects(session, campaign.tenant_id, campaign.id)
        _maybe_complete(session, campaign)
        return {"sent": True, "gmail_message_id": result.gmail_message_id}


@app.task(name="app.workers.tasks.campaign.classify_deliveries", bind=True)
def classify_deliveries(self, campaign_id: str | None = None) -> dict:
    """Sent + no bounce after the delay window -> Delivered (beat)."""
    cutoff = utcnow() - timedelta(hours=DELIVERY_DELAY_HOURS)
    updated = 0
    with worker_session() as session:
        stmt = select(EmailMessage).where(
            EmailMessage.status == MessageStatus.SENT.value,
            EmailMessage.sent_at.is_not(None),
            EmailMessage.sent_at <= cutoff,
            EmailMessage.bounced_at.is_(None),
        )
        if campaign_id is not None:
            stmt = stmt.where(EmailMessage.campaign_id == uuid.UUID(str(campaign_id)))
        messages = session.scalars(stmt).all()
        for message in messages:
            message.status = MessageStatus.DELIVERED.value
            message.delivered_at = utcnow()
            campaign = session.get(Campaign, message.campaign_id)
            if campaign is not None:
                stages_enqueue(session, campaign.tenant_id, "Outreach_Queue", str(message.id))
                sync_campaign_side_effects(session, campaign.tenant_id, campaign.id)
            updated += 1
    return {"delivered": updated}


def stages_enqueue(session, tenant_id, tab, key):
    from app.pipeline import stages

    stages._enqueue(session, tenant_id, tab, key)


def _maybe_complete(session, campaign: Campaign) -> None:
    """Flip a campaign to COMPLETED once no QUEUED messages remain."""
    remaining = session.scalar(
        select(EmailMessage.id)
        .where(
            EmailMessage.campaign_id == campaign.id,
            EmailMessage.status == MessageStatus.QUEUED.value,
        )
        .limit(1)
    )
    if remaining is None and campaign.status == CampaignStatus.SENDING.value:
        campaign.status = CampaignStatus.COMPLETED.value
        sync_campaign_side_effects(session, campaign.tenant_id, campaign.id)
