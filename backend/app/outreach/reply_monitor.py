"""Reply detection over Gmail threads (spec §14).

A reply is a thread that now holds more than one message where at least one is
NOT a DSN and comes from the recipient (i.e. not from our own send account). We
detect these by walking the thread of each SENT message and looking for an
inbound message that is neither the original send nor a delivery notice.

``detect_replies_for_campaign`` returns the EmailMessages that gained a reply,
so the task layer can persist :class:`ReplyEvent` rows and flip status.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MessageStatus
from app.models import Campaign, EmailMessage

__all__ = ["ReplyHit", "detect_replies_for_campaign", "thread_has_reply"]

# Statuses we will NOT overwrite with "replied" (already terminal/negative).
_LOCKED = {
    MessageStatus.HARD_BOUNCE.value,
    MessageStatus.BLOCKED.value,
    MessageStatus.SPAM_COMPLAINT.value,
    MessageStatus.UNSUBSCRIBED.value,
    MessageStatus.REPLIED.value,
}


@dataclass(slots=True)
class ReplyHit:
    email_message_id: object
    gmail_reply_id: str
    snippet: str | None


def _is_dsn_snippet(snippet: str | None) -> bool:
    if not snippet:
        return False
    low = snippet.lower()
    return "delivery status notification" in low or "mail delivery" in low or "undelivered" in low


def thread_has_reply(client, thread_id: str, sent_message_id: str) -> ReplyHit | None:
    """Return the first genuine reply in ``thread_id``, or None.

    A thread with >1 message qualifies only when one of the extra messages is a
    non-DSN inbound message (id differs from the original send).
    """
    messages = client.list_thread_messages(thread_id)
    if len(messages) <= 1:
        return None
    for m in messages:
        if m.id == sent_message_id:
            continue
        labels = getattr(m, "label_ids", []) or []
        # Our own SENT copy re-appears in the thread; skip it.
        if "SENT" in labels and "INBOX" not in labels:
            continue
        if _is_dsn_snippet(m.snippet):
            continue
        return ReplyHit(email_message_id=None, gmail_reply_id=m.id, snippet=m.snippet)
    return None


def detect_replies_for_campaign(session: Session, campaign: Campaign, client) -> list[ReplyHit]:
    """Find replies for all SENT-but-not-yet-replied messages in ``campaign``."""
    sent = session.scalars(
        select(EmailMessage).where(
            EmailMessage.campaign_id == campaign.id,
            EmailMessage.gmail_message_id.is_not(None),
            EmailMessage.replied_at.is_(None),
            EmailMessage.status.not_in(list(_LOCKED)),
        )
    ).all()
    hits: list[ReplyHit] = []
    for msg in sent:
        # Resolve the thread id via a metadata fetch of the sent message.
        try:
            meta = client.get_message(msg.gmail_message_id, format="minimal")
            thread_id = meta.thread_id
        except Exception:  # noqa: BLE001 - message may be gone; skip
            continue
        hit = thread_has_reply(client, thread_id, msg.gmail_message_id)
        if hit is not None:
            hit.email_message_id = msg.id
            hits.append(hit)
    return hits
