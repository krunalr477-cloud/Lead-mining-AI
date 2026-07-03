"""Send one queued EmailMessage through Gmail (spec §13).

``send_email_message`` renders is done at schedule time; here we:

- re-render strictly as a safety net (a literal ``{{X}}`` must never ship),
- append the unsubscribe footer and set the ``List-Unsubscribe`` header,
- stamp our own ``Message-ID`` (``<lm-{email_message_id}@domain>``) plus an
  ``X-LeadMine-Id`` header for deterministic bounce matching,
- debit the per-account send rate limiter (hour + day composite),
- send via the Gmail client, persist ``gmail_message_id`` + thread id, and flip
  the message to SENT.

Errors map to the task error taxonomy: a 429 is transient (auto-retried), and an
``invalid_grant`` is permanent and pauses the campaign (handled by the caller).
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import CampaignStatus, MessageStatus
from app.db import utcnow
from app.models import Campaign, CampaignSettings, EmailMessage
from app.workers.celery_app import PermanentError, TransientError

__all__ = ["SendResult", "append_unsubscribe_footer", "build_headers", "send_email_message"]

DEFAULT_UNSUB_TEXT = "If you'd prefer not to hear from us, reply with UNSUBSCRIBE."


class SendResult:
    """Outcome of a send attempt."""

    def __init__(
        self,
        *,
        sent: bool,
        gmail_message_id: str | None = None,
        thread_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.sent = sent
        self.gmail_message_id = gmail_message_id
        self.thread_id = thread_id
        self.error = error


def _own_domain() -> str:
    import re

    base = get_settings().app_base_url
    host = re.sub(r"^https?://", "", base).split("/")[0].split(":")[0]
    return host or "leadmine.local"


def append_unsubscribe_footer(body: str, unsub_text: str) -> str:
    """Append the opt-out footer, separated by a rule, if not already present."""
    text = (unsub_text or DEFAULT_UNSUB_TEXT).strip()
    if text and text in body:
        return body
    return f"{body.rstrip()}\n\n-- \n{text}"


def build_headers(
    email_message_id: uuid.UUID, from_account: str, unsub_text: str
) -> dict[str, str]:
    """RFC 822 headers for one message: Message-ID + List-Unsubscribe + tracer.

    The ``Message-ID`` is deterministic on the EmailMessage id so a returned DSN
    (which quotes the original Message-ID) matches back without a lookup table.
    ``List-Unsubscribe`` offers both a mailto and an app URL (RFC 8058-friendly).
    """
    domain = _own_domain()
    settings = get_settings()
    unsub_url = f"{settings.app_base_url}/unsubscribe?m={email_message_id}"
    mailto = f"mailto:{from_account}?subject={quote('unsubscribe')}"
    return {
        "Message-ID": f"<lm-{email_message_id}@{domain}>",
        "X-LeadMine-Id": str(email_message_id),
        "List-Unsubscribe": f"<{unsub_url}>, <{mailto}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "Auto-Submitted": "auto-generated",
    }


def _rate_limiter(from_account: str, campaign: Campaign):
    from app.workers.rate_limit import bucket_for_send_account

    return bucket_for_send_account(
        from_account,
        per_hour=campaign.rate_limit_per_hour or 100,
        per_day=campaign.rate_limit_per_day or 300,
    )


def send_email_message(
    session: Session,
    message: EmailMessage,
    *,
    client=None,
    enforce_rate_limit: bool = True,
) -> SendResult:
    """Render, stamp, and send ``message``; persist Gmail ids; flip to SENT.

    ``client`` may be injected (tests); otherwise it is resolved from the
    campaign's tenant + from_account. Raises :class:`TransientError` on a rate-
    limit denial or 429 (auto-retried), and :class:`PermanentError` on
    ``invalid_grant`` so the caller can pause the campaign.
    """
    campaign = session.get(Campaign, message.campaign_id)
    if campaign is None:
        raise PermanentError("campaign missing for message")

    settings_row = session.scalar(
        __import__("sqlalchemy")
        .select(CampaignSettings)
        .where(CampaignSettings.tenant_id == campaign.tenant_id)
    )
    unsub_text = settings_row.unsubscribe_text if settings_row else DEFAULT_UNSUB_TEXT

    # Strict re-render safety net: message.subject/body were rendered at schedule
    # time, but re-validate that no literal placeholder survives.
    subject = _safe_render(message.subject)
    body = append_unsubscribe_footer(_safe_render(message.body), unsub_text)

    headers = build_headers(message.id, campaign.from_account, unsub_text)

    if client is None:
        from app.adapters.google.gmail_client import get_gmail_client

        client = get_gmail_client(campaign.tenant_id, session, campaign.from_account)

    if enforce_rate_limit:
        limiter = _rate_limiter(campaign.from_account, campaign)
        if not limiter.acquire(1):
            raise TransientError("send rate limit reached for account")

    try:
        result = client.send(to=message.to_email, subject=subject, body=body, headers=headers)
    except PermanentError:
        # invalid_grant etc. — pause the campaign so the operator re-auths.
        campaign.status = CampaignStatus.PAUSED.value
        session.flush()
        raise
    except TransientError:
        raise

    message.gmail_message_id = result.id
    message.status = MessageStatus.SENT.value
    message.sent_at = utcnow()
    session.flush()
    return SendResult(sent=True, gmail_message_id=result.id, thread_id=result.thread_id)


def _safe_render(text: str) -> str:
    """Render with an empty context: if any ``{{X}}`` remains, it's a failure."""
    from app.outreach.renderer import used_variables

    if not used_variables(text):
        return text
    # A scheduled message should already be fully rendered; a surviving variable
    # means bad data — fail loudly rather than ship a literal placeholder.
    raise PermanentError(f"unrendered template variables in message: {used_variables(text)}")
