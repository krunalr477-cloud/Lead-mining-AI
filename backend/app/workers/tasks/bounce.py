"""bounce_check_jobs queue — poll Gmail for DSNs and replies (spec §14).

- ``poll_bounces`` (beat: every ``bounce_poll_interval_minutes``) — for each
  tenant with active sending, query ``from:(mailer-daemon OR postmaster)
  newer_than:3d``, fetch each notice raw, parse it, match it back to the
  originating :class:`EmailMessage`, and apply the bounce action set.
- ``poll_replies`` — walk SENT messages' threads for genuine replies.
- After every detection the affected sheet tabs are re-synced (enqueued by the
  suppression/reply appliers) and flushed.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import CampaignStatus, MessageStatus
from app.db import utcnow
from app.models import Campaign, EmailMessage
from app.outreach.bounce_parser import parse_dsn
from app.outreach.reply_monitor import detect_replies_for_campaign
from app.outreach.suppression import apply_bounce, apply_reply
from app.workers.celery_app import app
from app.workers.tasks._base import worker_session

__all__ = ["match_message", "poll_bounces", "poll_replies"]

# Bounces arrive within minutes; we correlate the DSN's detection time to a send
# within this window as a secondary signal when Message-ID matching is ambiguous.
_MATCH_WINDOW = timedelta(days=3)
_LM_ID_RE = re.compile(r"lm-([0-9a-fA-F-]{36})@")

_ACTIVE = {
    CampaignStatus.SENDING.value,
    CampaignStatus.QUEUED.value,
    CampaignStatus.SCHEDULED.value,
    CampaignStatus.PAUSED.value,
    CampaignStatus.COMPLETED.value,
}

DAEMON_QUERY = "from:(mailer-daemon OR postmaster) newer_than:3d"


def _tenants_with_campaigns(session: Session) -> list[tuple[uuid.UUID, str]]:
    """Distinct (tenant_id, from_account) pairs that have sent messages."""
    rows = session.execute(
        select(Campaign.tenant_id, Campaign.from_account)
        .where(Campaign.status.in_(list(_ACTIVE)))
        .distinct()
    ).all()
    return [(tid, acct) for (tid, acct) in rows]


def match_message(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    original_message_id: str | None,
    recipient: str | None,
) -> EmailMessage | None:
    """Match a parsed DSN back to its EmailMessage.

    Primary key: our own ``<lm-{uuid}@domain>`` Message-ID quoted in the DSN.
    Fallbacks: exact ``gmail_message_id`` string, then recent-send-to-recipient
    within the match window.
    """
    # 1. Our deterministic Message-ID carries the EmailMessage UUID.
    if original_message_id:
        m = _LM_ID_RE.search(original_message_id)
        if m:
            try:
                em_id = uuid.UUID(m.group(1))
            except ValueError:
                em_id = None
            if em_id is not None:
                msg = session.get(EmailMessage, em_id)
                if msg is not None and _belongs_to_tenant(session, msg, tenant_id):
                    return msg
        # 2. Some servers echo the Gmail message id instead.
        by_gmail = session.scalar(
            select(EmailMessage)
            .join(Campaign, EmailMessage.campaign_id == Campaign.id)
            .where(
                Campaign.tenant_id == tenant_id,
                EmailMessage.gmail_message_id == original_message_id,
            )
        )
        if by_gmail is not None:
            return by_gmail

    # 3. Recent SENT message to the same recipient.
    if recipient:
        since = utcnow() - _MATCH_WINDOW
        return session.scalar(
            select(EmailMessage)
            .join(Campaign, EmailMessage.campaign_id == Campaign.id)
            .where(
                Campaign.tenant_id == tenant_id,
                EmailMessage.to_email.ilike(recipient),
                EmailMessage.sent_at.is_not(None),
                EmailMessage.sent_at >= since,
            )
            .order_by(EmailMessage.sent_at.desc())
        )
    return None


def _belongs_to_tenant(session: Session, message: EmailMessage, tenant_id: uuid.UUID) -> bool:
    campaign = session.get(Campaign, message.campaign_id)
    return campaign is not None and campaign.tenant_id == tenant_id


def _flush_sheets(session: Session, tenant_id: uuid.UUID) -> None:
    """Flush the DB->Sheets mirror for the tabs touched by bounce/reply actions."""
    from app.sheetsync.engine import SheetSyncEngine
    from app.sheetsync.factory import get_sheets_client

    client = get_sheets_client(tenant_id, session)
    engine = SheetSyncEngine(session, client)
    engine.setup_spreadsheet(tenant_id)
    for tab in (
        "Outreach_Queue",
        "Bounce_Log",
        "Suppression_List",
        "Sales_Ready_Leads",
        "Campaigns",
        "Contacts",
    ):
        engine.flush_tab(tenant_id, tab)


@app.task(name="app.workers.tasks.bounce.poll_bounces", bind=True)
def poll_bounces(self, tenant_id: str | None = None, from_account: str | None = None) -> dict:
    """Poll DSNs, parse, match, and apply bounce actions for active senders."""
    processed = 0
    matched = 0
    with worker_session() as session:
        if tenant_id is not None and from_account is not None:
            pairs = [(uuid.UUID(str(tenant_id)), from_account)]
        else:
            pairs = _tenants_with_campaigns(session)
        for tid, account in pairs:
            from app.adapters.google.gmail_client import get_gmail_client

            client = get_gmail_client(tid, session, account)
            notices = client.list_messages(DAEMON_QUERY, max_results=100)
            touched = False
            for notice in notices:
                full = client.get_message(notice.id, format="raw")
                if not full.raw:
                    continue
                processed += 1
                info = parse_dsn(full.raw)
                message = match_message(
                    session,
                    tid,
                    original_message_id=info.original_message_id,
                    recipient=info.final_recipient,
                )
                if message is None:
                    continue
                # Skip if we already recorded a bounce for this message.
                if message.bounced_at is not None and message.status in (
                    MessageStatus.HARD_BOUNCE.value,
                    MessageStatus.SPAM_COMPLAINT.value,
                    MessageStatus.BLOCKED.value,
                ):
                    continue
                apply_bounce(session, message, info)
                matched += 1
                touched = True
            if touched:
                _flush_sheets(session, tid)
    return {"processed": processed, "matched": matched}


@app.task(name="app.workers.tasks.bounce.poll_replies", bind=True)
def poll_replies(self, tenant_id: str | None = None) -> dict:
    """Detect replies across SENT messages and mark them REPLIED."""
    detected = 0
    with worker_session() as session:
        stmt = select(Campaign).where(Campaign.status.in_(list(_ACTIVE)))
        if tenant_id is not None:
            stmt = stmt.where(Campaign.tenant_id == uuid.UUID(str(tenant_id)))
        campaigns = session.scalars(stmt).all()
        touched_tenants: set[uuid.UUID] = set()
        for campaign in campaigns:
            from app.adapters.google.gmail_client import get_gmail_client

            client = get_gmail_client(campaign.tenant_id, session, campaign.from_account)
            hits = detect_replies_for_campaign(session, campaign, client)
            for hit in hits:
                message = session.get(EmailMessage, hit.email_message_id)
                if message is None:
                    continue
                apply_reply(
                    session, message, gmail_reply_id=hit.gmail_reply_id, snippet=hit.snippet
                )
                detected += 1
                touched_tenants.add(campaign.tenant_id)
        for tid in touched_tenants:
            _flush_sheets(session, tid)
    return {"replies": detected}
