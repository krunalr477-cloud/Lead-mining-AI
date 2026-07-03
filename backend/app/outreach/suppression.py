"""Suppression + bounce/reply side-effects (spec §14 Actions, §25 criterion 11).

Central place where a detected bounce/reply mutates state so the rules live in
one spot:

- **Hard bounce** -> mark the EmailMessage HARD_BOUNCE, add a permanent
  :class:`Suppression`, flip the Contact to SUPPRESSED, tombstone the matching
  :class:`SalesReadyLead`, and enqueue sheet upserts.
- **Soft bounce** -> mark SOFT_BOUNCE; suppress only after the retry budget is
  exhausted (repeated soft bounces).
- **Spam / unsubscribe** -> immediate permanent suppression + terminal status.
- **Reply** -> mark REPLIED (unless already terminal-negative).

Every state change enqueues upserts for the affected sheet tabs
(Outreach_Queue / Bounce_Log / Suppression_List / Sales_Ready_Leads / Campaigns)
via the sheet-sync engine's DB-only ``enqueue_upsert`` hook.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import BounceType, FinalEmailStatus, MessageStatus
from app.db import utcnow
from app.models import (
    BounceEvent,
    Campaign,
    Contact,
    EmailMessage,
    ReplyEvent,
    SalesReadyLead,
    Suppression,
)
from app.outreach.bounce_parser import BounceInfo

__all__ = [
    "SOFT_BOUNCE_RETRY_BUDGET",
    "apply_bounce",
    "apply_reply",
    "ensure_suppressed",
    "sync_campaign_side_effects",
]

# A soft-bouncing address is suppressed after this many soft bounces (spec §14
# "retry based on policy, then suppress if repeated").
SOFT_BOUNCE_RETRY_BUDGET = 3


def _enqueue(session: Session, tenant_id: uuid.UUID, tab: str, row_key: str) -> None:
    """DB-only sheet upsert (no client I/O) — mirrors pipeline.stages._enqueue."""
    from app.sheetsync.client import FakeSheetsClient
    from app.sheetsync.engine import SheetSyncEngine

    engine = SheetSyncEngine(session, FakeSheetsClient(tenant_id, persist=False))
    engine.enqueue_upsert(session, tenant_id, tab, row_key)


def _tenant_of(session: Session, message: EmailMessage) -> uuid.UUID:
    campaign = session.get(Campaign, message.campaign_id)
    return campaign.tenant_id if campaign else message.campaign_id


def ensure_suppressed(
    session: Session,
    tenant_id: uuid.UUID,
    email: str,
    *,
    reason: str,
    source: str,
    permanent: bool = True,
) -> Suppression | None:
    """Add a permanent (or active) address suppression if not already present."""
    if not email:
        return None
    existing = session.scalar(
        select(Suppression).where(
            Suppression.tenant_id == tenant_id,
            func.lower(Suppression.email) == email.lower(),
        )
    )
    if existing is not None:
        if permanent and not existing.permanent:
            existing.permanent = True
            session.flush()
        return existing
    supp = Suppression(
        tenant_id=tenant_id,
        email=email,
        domain=None,
        reason=reason,
        source=source,
        permanent=permanent,
    )
    session.add(supp)
    session.flush()
    _enqueue(session, tenant_id, "Suppression_List", supp.email)
    return supp


def _tombstone_leads(session: Session, tenant_id: uuid.UUID, email: str) -> list[SalesReadyLead]:
    """Tombstone every sales-ready lead with this address (never re-surfaced)."""
    leads = session.scalars(
        select(SalesReadyLead).where(
            SalesReadyLead.tenant_id == tenant_id,
            func.lower(SalesReadyLead.email) == email.lower(),
        )
    ).all()
    for lead in leads:
        lead.tombstoned = True
        lead.campaign_status = "bounced"
        _enqueue(session, tenant_id, "Sales_Ready_Leads", str(lead.id))
    return leads


def _suppress_contact(session: Session, contact_id: uuid.UUID | None, tenant_id: uuid.UUID) -> None:
    if contact_id is None:
        return
    contact = session.get(Contact, contact_id)
    if contact is not None:
        contact.final_email_status = FinalEmailStatus.SUPPRESSED.value
        contact.sales_ready = False
        session.flush()
        _enqueue(session, tenant_id, "Contacts", str(contact.id))


def _record_bounce_event(
    session: Session,
    message: EmailMessage,
    info: BounceInfo,
    tenant_id: uuid.UUID,
) -> BounceEvent:
    event = BounceEvent(
        email_message_id=message.id,
        contact_id=message.contact_id,
        email=info.final_recipient or message.to_email,
        smtp_status_code=info.smtp_status,
        bounce_type=info.bounce_type.value,
        diagnostic_code=info.diagnostic_code,
        reason=info.reason,
        raw_message_reference=info.original_message_id,
        detected_at=utcnow(),
    )
    session.add(event)
    session.flush()
    _enqueue(session, tenant_id, "Bounce_Log", str(event.id))
    return event


def _soft_bounce_count(session: Session, tenant_id: uuid.UUID, email: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(BounceEvent)
            .join(EmailMessage, BounceEvent.email_message_id == EmailMessage.id)
            .join(Campaign, EmailMessage.campaign_id == Campaign.id)
            .where(
                Campaign.tenant_id == tenant_id,
                func.lower(BounceEvent.email) == email.lower(),
                BounceEvent.bounce_type == BounceType.SOFT.value,
            )
        )
        or 0
    )


def apply_bounce(session: Session, message: EmailMessage, info: BounceInfo) -> dict:
    """Apply the full bounce action set for ``message`` given parsed ``info``.

    Returns a small summary describing what changed (for logging/audit).
    """
    tenant_id = _tenant_of(session, message)
    email = info.final_recipient or message.to_email
    event = _record_bounce_event(session, message, info, tenant_id)

    bt = info.bounce_type
    is_hard = bt in (
        BounceType.HARD,
        BounceType.INVALID_DOMAIN,
        BounceType.MAILBOX_FULL,
    )
    is_spam = bt == BounceType.SPAM_REJECTED
    is_blocked = bt == BounceType.BLOCKED

    now: datetime = utcnow()
    summary: dict = {"email": email, "bounce_type": bt.value, "action": None}

    if is_spam:
        message.status = MessageStatus.SPAM_COMPLAINT.value
        message.bounced_at = now
        ensure_suppressed(
            session,
            tenant_id,
            email,
            reason=info.reason or "Spam rejection",
            source="bounce_parser",
            permanent=True,
        )
        _suppress_contact(session, message.contact_id, tenant_id)
        _tombstone_leads(session, tenant_id, email)
        summary["action"] = "suppressed_spam"
    elif is_hard:
        message.status = MessageStatus.HARD_BOUNCE.value
        message.bounced_at = now
        ensure_suppressed(
            session,
            tenant_id,
            email,
            reason=info.reason or f"Hard bounce {info.smtp_status or ''}".strip(),
            source="bounce_parser",
            permanent=True,
        )
        _suppress_contact(session, message.contact_id, tenant_id)
        _tombstone_leads(session, tenant_id, email)
        summary["action"] = "suppressed_hard"
    elif is_blocked:
        message.status = MessageStatus.BLOCKED.value
        message.bounced_at = now
        # Blocked is treated as hard for suppression (repeated blocks won't clear).
        ensure_suppressed(
            session,
            tenant_id,
            email,
            reason=info.reason or "Blocked by recipient server",
            source="bounce_parser",
            permanent=True,
        )
        _suppress_contact(session, message.contact_id, tenant_id)
        _tombstone_leads(session, tenant_id, email)
        summary["action"] = "suppressed_blocked"
    else:
        # Soft / rate-limited / unknown -> soft bounce with retry budget.
        message.status = MessageStatus.SOFT_BOUNCE.value
        message.bounced_at = now
        soft_count = _soft_bounce_count(session, tenant_id, email)
        if soft_count >= SOFT_BOUNCE_RETRY_BUDGET:
            ensure_suppressed(
                session,
                tenant_id,
                email,
                reason=f"Repeated soft bounces ({soft_count})",
                source="bounce_parser",
                permanent=True,
            )
            _suppress_contact(session, message.contact_id, tenant_id)
            _tombstone_leads(session, tenant_id, email)
            summary["action"] = "suppressed_soft_exhausted"
        else:
            summary["action"] = f"soft_retry ({soft_count}/{SOFT_BOUNCE_RETRY_BUDGET})"

    session.flush()
    _enqueue(session, tenant_id, "Outreach_Queue", str(message.id))
    _enqueue(session, tenant_id, "Campaigns", str(message.campaign_id))
    summary["bounce_event_id"] = str(event.id)
    return summary


def apply_reply(
    session: Session, message: EmailMessage, *, gmail_reply_id: str, snippet: str | None
) -> dict:
    """Mark ``message`` REPLIED and record a :class:`ReplyEvent`."""
    tenant_id = _tenant_of(session, message)
    # Don't overwrite a terminal-negative status.
    locked = {
        MessageStatus.HARD_BOUNCE.value,
        MessageStatus.BLOCKED.value,
        MessageStatus.SPAM_COMPLAINT.value,
        MessageStatus.UNSUBSCRIBED.value,
    }
    already = session.scalar(select(ReplyEvent).where(ReplyEvent.email_message_id == message.id))
    if already is None:
        session.add(
            ReplyEvent(
                email_message_id=message.id,
                contact_id=message.contact_id,
                gmail_message_id=gmail_reply_id,
                snippet=snippet,
                detected_at=utcnow(),
            )
        )
    if message.replied_at is None:
        message.replied_at = utcnow()
    if message.status not in locked:
        message.status = MessageStatus.REPLIED.value
    session.flush()
    _enqueue(session, tenant_id, "Outreach_Queue", str(message.id))
    _enqueue(session, tenant_id, "Campaigns", str(message.campaign_id))
    return {"email_message_id": str(message.id), "action": "replied"}


def sync_campaign_side_effects(
    session: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """Enqueue Campaigns-tab upsert (called when campaign status changes)."""
    _enqueue(session, tenant_id, "Campaigns", str(campaign_id))
