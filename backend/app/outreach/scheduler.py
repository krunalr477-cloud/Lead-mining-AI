"""Campaign scheduling + per-recipient eligibility (spec §13 / §25 HARD rule).

On launch we re-derive the recipient list from the campaign's mining job (or the
whole tenant if unscoped) and, **per recipient**, re-check eligibility:

- ``final_email_status == VERIFIED`` (spec §25: never send to invalid/review),
- not suppressed (address OR domain, permanent or active),
- not already bounced / unsubscribed / replied in a prior message,
- passes the job's role-include filter (``contact_roles``) and
  exclude-keyword filter (``exclude_keywords``).

Eligible recipients get an :class:`EmailMessage` row (status QUEUED) with a
``scheduled_at`` spread across the tenant's send window at
``rate_limit_per_hour``. ``estimate_completion`` reports recipients / rate.

Pure-ish: everything takes an explicit sync Session; no Celery, no network.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import FinalEmailStatus, MessageStatus
from app.db import utcnow
from app.models import (
    Campaign,
    CampaignSettings,
    Company,
    Contact,
    EmailMessage,
    HiringSignal,
    Suppression,
)
from app.outreach.renderer import RecipientFacts, build_context, render

__all__ = [
    "EligibilityReason",
    "RecipientDecision",
    "build_recipient_facts",
    "estimate_completion",
    "plan_recipients",
    "schedule_campaign",
]


class EligibilityReason:
    """Why a candidate was rejected (stable strings for the eligibility summary)."""

    NOT_VERIFIED = "not_verified"
    SUPPRESSED = "suppressed"
    ALREADY_BOUNCED = "already_bounced"
    ALREADY_REPLIED = "already_replied"
    ALREADY_UNSUBSCRIBED = "already_unsubscribed"
    ROLE_FILTERED = "role_filtered"
    EXCLUDED_KEYWORD = "excluded_keyword"
    NO_EMAIL = "no_email"
    RENDER_FAILED = "render_failed"


@dataclass(slots=True)
class RecipientDecision:
    contact_id: uuid.UUID
    email: str
    eligible: bool
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Eligibility                                                                  #
# --------------------------------------------------------------------------- #


def _suppressed_targets(session: Session, tenant_id: uuid.UUID) -> tuple[set[str], set[str]]:
    """Return (suppressed emails lowercased, suppressed domains lowercased)."""
    rows = session.execute(
        select(Suppression.email, Suppression.domain).where(Suppression.tenant_id == tenant_id)
    ).all()
    emails = {e.lower() for (e, _d) in rows if e}
    domains = {d.lower() for (_e, d) in rows if d}
    return emails, domains


def _prior_terminal_emails(session: Session, tenant_id: uuid.UUID) -> dict[str, str]:
    """Emails with a prior terminal outcome anywhere in this tenant.

    Maps lowercased email -> reason (bounced / replied / unsubscribed), so a
    contact that already hard-bounced or opted out in a previous campaign is
    never re-targeted.
    """
    terminal = {
        MessageStatus.HARD_BOUNCE.value: EligibilityReason.ALREADY_BOUNCED,
        MessageStatus.SOFT_BOUNCE.value: EligibilityReason.ALREADY_BOUNCED,
        MessageStatus.BLOCKED.value: EligibilityReason.ALREADY_BOUNCED,
        MessageStatus.SPAM_COMPLAINT.value: EligibilityReason.ALREADY_UNSUBSCRIBED,
        MessageStatus.UNSUBSCRIBED.value: EligibilityReason.ALREADY_UNSUBSCRIBED,
        MessageStatus.REPLIED.value: EligibilityReason.ALREADY_REPLIED,
    }
    rows = session.execute(
        select(EmailMessage.to_email, EmailMessage.status)
        .join(Campaign, EmailMessage.campaign_id == Campaign.id)
        .where(Campaign.tenant_id == tenant_id, EmailMessage.status.in_(list(terminal)))
    ).all()
    out: dict[str, str] = {}
    for email, status in rows:
        if not email:
            continue
        reason = terminal[status]
        # Bounce/unsubscribe outrank a mere reply for gating purposes: a non-reply
        # reason always wins; a reply only fills an empty slot.
        low = email.lower()
        if reason != EligibilityReason.ALREADY_REPLIED or low not in out:
            out[low] = reason
    return out


def _role_ok(contact: Contact, include_roles: list[str], exclude_keywords: list[str]) -> str | None:
    """Return a rejection reason if the contact fails role filters, else None."""
    haystack = " ".join(
        str(v).lower()
        for v in (contact.designation, contact.role_category, contact.seniority, contact.department)
        if v
    )
    for kw in exclude_keywords:
        if kw and kw.lower() in haystack:
            return EligibilityReason.EXCLUDED_KEYWORD
    if include_roles and not any(role and role.lower() in haystack for role in include_roles):
        return EligibilityReason.ROLE_FILTERED
    return None


def build_recipient_facts(
    contact: Contact, company: Company | None, hiring_signal: HiringSignal | None
) -> RecipientFacts:
    """Assemble the template-variable facts for one recipient."""
    services = ", ".join(company.services) if company and company.services else None
    hiring = None
    if hiring_signal is not None:
        hiring = hiring_signal.job_title or hiring_signal.description_excerpt
    return RecipientFacts(
        first_name=contact.first_name,
        last_name=contact.last_name,
        full_name=contact.full_name,
        company=company.canonical_name if company else None,
        industry=company.industry if company else None,
        city=company.city if company else None,
        state=company.state if company else None,
        country=company.country if company else None,
        services=services,
        designation=contact.designation,
        website=company.website if company else None,
        hiring_signal=hiring,
    )


def plan_recipients(session: Session, campaign: Campaign) -> list[RecipientDecision]:
    """Evaluate every candidate contact for the campaign; return decisions.

    Candidates are the tenant's contacts (scoped to the campaign's mining job
    when set). Each is checked against the §25 HARD eligibility rule.
    """
    tenant_id = campaign.tenant_id
    stmt = select(Contact).where(Contact.tenant_id == tenant_id)
    if campaign.job_id is not None:
        stmt = stmt.where(Contact.job_id == campaign.job_id)
    contacts = session.scalars(stmt.order_by(Contact.created_at)).all()

    supp_emails, supp_domains = _suppressed_targets(session, tenant_id)
    prior_terminal = _prior_terminal_emails(session, tenant_id)

    include_roles: list[str] = []
    exclude_keywords: list[str] = []
    if campaign.job_id is not None:
        from app.models import MiningJob

        job = session.get(MiningJob, campaign.job_id)
        if job is not None:
            include_roles = list(job.contact_roles or [])
            exclude_keywords = list(job.exclude_keywords or [])

    decisions: list[RecipientDecision] = []
    seen_emails: set[str] = set()
    for contact in contacts:
        email = (contact.email or "").strip()
        if not email:
            decisions.append(RecipientDecision(contact.id, "", False, EligibilityReason.NO_EMAIL))
            continue
        low = email.lower()
        # De-dupe: one message per distinct address per campaign.
        if low in seen_emails:
            continue
        seen_emails.add(low)

        reason = _eligibility_reason(
            contact,
            email,
            supp_emails,
            supp_domains,
            prior_terminal,
            include_roles,
            exclude_keywords,
        )
        decisions.append(RecipientDecision(contact.id, email, reason is None, reason))
    return decisions


def _eligibility_reason(
    contact: Contact,
    email: str,
    supp_emails: set[str],
    supp_domains: set[str],
    prior_terminal: dict[str, str],
    include_roles: list[str],
    exclude_keywords: list[str],
) -> str | None:
    low = email.lower()
    if contact.final_email_status != FinalEmailStatus.VERIFIED.value:
        return EligibilityReason.NOT_VERIFIED
    domain = low.split("@", 1)[1] if "@" in low else ""
    if low in supp_emails or (domain and domain in supp_domains):
        return EligibilityReason.SUPPRESSED
    if low in prior_terminal:
        return prior_terminal[low]
    role_reason = _role_ok(contact, include_roles, exclude_keywords)
    if role_reason is not None:
        return role_reason
    return None


# --------------------------------------------------------------------------- #
# Scheduling                                                                   #
# --------------------------------------------------------------------------- #


def _send_settings(session: Session, campaign: Campaign) -> CampaignSettings | None:
    return session.scalar(
        select(CampaignSettings).where(CampaignSettings.tenant_id == campaign.tenant_id)
    )


def _in_window(dt: datetime, start: time, end: time) -> bool:
    return start <= dt.time() <= end


def _advance_to_window(dt: datetime, start: time, end: time) -> datetime:
    """Move ``dt`` forward to the next moment inside [start, end]."""
    if dt.time() < start:
        return dt.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    if dt.time() > end:
        nxt = (dt + timedelta(days=1)).replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
        return nxt
    return dt


def assign_schedule(
    count: int,
    *,
    rate_per_hour: int,
    start_at: datetime,
    window_start: time,
    window_end: time,
) -> list[datetime]:
    """Return ``count`` send timestamps spread at ``rate_per_hour`` in-window.

    The spacing is 3600/rate seconds; timestamps that fall past the daily window
    roll to the next day's window start.
    """
    if count <= 0:
        return []
    rate = max(1, rate_per_hour)
    interval = timedelta(seconds=3600.0 / rate)
    out: list[datetime] = []
    cursor = _advance_to_window(start_at, window_start, window_end)
    for _ in range(count):
        cursor = _advance_to_window(cursor, window_start, window_end)
        out.append(cursor)
        cursor = cursor + interval
    return out


def estimate_completion(count: int, rate_per_hour: int) -> dict:
    """Estimated wall-clock to send ``count`` messages at ``rate_per_hour``."""
    rate = max(1, rate_per_hour)
    hours = count / rate
    return {
        "recipient_count": count,
        "rate_per_hour": rate,
        "estimated_hours": round(hours, 2),
        "estimated_completion_at": (utcnow() + timedelta(hours=hours)).isoformat(),
    }


def schedule_campaign(session: Session, campaign: Campaign) -> dict:
    """Materialize QUEUED EmailMessage rows for every eligible recipient.

    Idempotent: existing messages for the campaign are cleared and rebuilt, so a
    re-launch re-checks eligibility from scratch. Returns a summary including the
    eligibility breakdown and completion estimate.
    """
    # Rebuild the recipient set from scratch.
    session.query(EmailMessage).filter(EmailMessage.campaign_id == campaign.id).delete()
    session.flush()

    decisions = plan_recipients(session, campaign)
    eligible = [d for d in decisions if d.eligible]

    settings = _send_settings(session, campaign)
    rate = campaign.rate_limit_per_hour or (settings.send_limit_per_hour if settings else 100)
    window_start = settings.send_window_start if settings else time(9, 0)
    window_end = settings.send_window_end if settings else time(18, 0)

    schedule = assign_schedule(
        len(eligible),
        rate_per_hour=rate,
        start_at=utcnow(),
        window_start=window_start,
        window_end=window_end,
    )

    # Prefetch contacts + companies for facts/rendering.
    contact_ids = [d.contact_id for d in eligible]
    contacts = (
        {c.id: c for c in session.scalars(select(Contact).where(Contact.id.in_(contact_ids))).all()}
        if contact_ids
        else {}
    )

    created = 0
    render_failures = 0
    for decision, when in zip(eligible, schedule, strict=False):
        contact = contacts.get(decision.contact_id)
        if contact is None:
            continue
        company = session.get(Company, contact.company_id) if contact.company_id else None
        signal = None
        if company is not None:
            signal = session.scalar(
                select(HiringSignal)
                .where(HiringSignal.company_id == company.id)
                .order_by(HiringSignal.id)
                .limit(1)
            )
        facts = build_recipient_facts(contact, company, signal)
        ctx = build_context(facts)
        try:
            subject = render(campaign.subject_template, ctx)
            body = render(campaign.body_template, ctx)
        except Exception:  # noqa: BLE001 - strict renderer: drop this recipient
            render_failures += 1
            decision.eligible = False
            decision.reason = EligibilityReason.RENDER_FAILED
            continue
        session.add(
            EmailMessage(
                campaign_id=campaign.id,
                contact_id=contact.id,
                to_email=decision.email,
                subject=subject,
                body=body,
                status=MessageStatus.QUEUED.value,
                scheduled_at=when,
            )
        )
        created += 1
    session.flush()

    breakdown: dict[str, int] = {}
    for d in decisions:
        if d.reason:
            breakdown[d.reason] = breakdown.get(d.reason, 0) + 1

    return {
        "recipient_count": created,
        "candidates": len(decisions),
        "rejected": breakdown,
        "render_failures": render_failures,
        **estimate_completion(created, rate),
    }


def count_verified_eligible(session: Session, campaign: Campaign) -> int:
    """Cheap pre-flight count of eligible recipients (for the launch guard)."""
    return sum(1 for d in plan_recipients(session, campaign) if d.eligible)
