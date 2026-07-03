"""Idempotent Ahmedabad-CA-firms demo seed (spec §21).

``seed_demo()`` provisions the "Demo Workspace" tenant, its admin user, the
per-tenant settings (validation rules, campaign limits, data-source compliance
gates), and the flagship mining job with the exact spec §21 parameters. It then
runs the whole mock pipeline inline (``run_job_inline``) so the DB fills with
real Company/Contact/EmailCandidate/ValidationCheck/SalesReadyLead rows produced
by the actual mock adapters + validation decision machine + sheet-mirror engine.

Finally it seeds one COMPLETED outreach campaign — synthetic sent/delivered/
opened/replied/bounced EmailMessages plus the matching BounceEvent, Suppression,
and ReplyEvent rows — so the dashboard, bounce, and campaign screens are
populated before the real sender lands in Phase 7. Suppressing the hard bounces
also tombstones the affected Sales_Ready_Leads, demonstrating criterion 11/25
(invalid/bounced addresses never remain sales-ready).

Idempotency: every top-level row is upserted by a fixed UUID, so re-running the
seed reconciles in place rather than duplicating. The mock pipeline is itself
deterministic (seeded from the fixed job_id), so the funnel reproduces exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.constants import (
    AccessMethod,
    BounceType,
    CampaignStatus,
    FinalEmailStatus,
    JobStatus,
    MessageStatus,
    Posture,
    Role,
    SourceName,
)
from app.db import sync_session_factory, utcnow
from app.models import (
    AuditLog,
    BounceEvent,
    Campaign,
    CampaignSettings,
    Company,
    Contact,
    DataSourceConfig,
    EmailMessage,
    EmailTemplate,
    MiningJob,
    ReplyEvent,
    SalesReadyLead,
    Suppression,
    Tenant,
    User,
    ValidationRuleSet,
)
from app.models.settings_models import default_validation_rules
from app.pipeline.orchestrator import compute_totals, recompute_and_persist_totals, run_job_inline
from app.pipeline.stages import recompute_sales_ready_for_job, run_sync

__all__ = ["DEMO_IDS", "seed_demo"]

# Fixed UUIDs so the seed is idempotent (upsert-by-id) across re-runs.
DEMO_IDS = {
    "tenant": uuid.UUID("00000000-0000-0000-0000-0000000d3010"),
    "user": uuid.UUID("00000000-0000-0000-0000-0000000d3011"),
    "rules": uuid.UUID("00000000-0000-0000-0000-0000000d3012"),
    "campaign_settings": uuid.UUID("00000000-0000-0000-0000-0000000d3013"),
    "job": uuid.UUID("00000000-0000-0000-0000-0000000d3020"),
    "template": uuid.UUID("00000000-0000-0000-0000-0000000d3030"),
    "campaign": uuid.UUID("00000000-0000-0000-0000-0000000d3031"),
    "audit_job": uuid.UUID("00000000-0000-0000-0000-0000000d3040"),
    "audit_signoff": uuid.UUID("00000000-0000-0000-0000-0000000d3041"),
    "audit_campaign": uuid.UUID("00000000-0000-0000-0000-0000000d3042"),
}

from app.constants import DEMO_ADMIN_EMAIL, DEMO_TENANT_NAME  # noqa: E402  (shared identity)

DEMO_JOB_NAME = "Ahmedabad CA Firms — Audit & Tax"

# Spec §21 job parameters (verbatim).
_JOB_SPEC = {
    "company_type": "CA Firm",
    "services": ["Audit", "Tax Filing"],
    "country": "India",
    "state": "Gujarat",
    "city": "Ahmedabad",
    "latitude": 23.0225,
    "longitude": 72.5714,
    "radius_km": 20,
    "company_size_min": 50,
    "company_size_max": 200,
    "contact_roles": ["Founder", "CEO", "Managing Partner", "Director", "Partner"],
    "exclude_keywords": ["HR", "Careers", "Jobs", "Intern", "Support"],
    "selected_sources": [
        SourceName.GOOGLE_MAPS.value,
        SourceName.COMPANY_WEBSITES.value,
        SourceName.DIRECTORIES.value,
        SourceName.FACEBOOK_SIGNALS.value,
    ],
}

# Data-source compliance matrix (spec §8). GREEN sources enabled; the AMBER
# facebook/serp signal sources are present + enabled (signed off for the demo);
# yellow_pages/clutch (AMBER) and indeed/linkedin (RED) present but disabled.
_SOURCE_CONFIGS: list[dict] = [
    {
        "source": SourceName.GOOGLE_MAPS,
        "posture": Posture.GREEN,
        "enabled": True,
        "signoff": False,
        "note": "Google Maps Platform Places API (official).",
    },
    {
        "source": SourceName.COMPANY_WEBSITES,
        "posture": Posture.GREEN,
        "enabled": True,
        "signoff": False,
        "note": "Polite crawl of public company pages.",
    },
    {
        "source": SourceName.DIRECTORIES,
        "posture": Posture.GREEN,
        "enabled": True,
        "signoff": False,
        "note": "Open/licensed public business directories.",
    },
    {
        "source": SourceName.FACEBOOK_SIGNALS,
        "posture": Posture.AMBER,
        "enabled": True,
        "signoff": True,
        "note": "Public hiring-signal mode only (compliant, no scraping).",
    },
    {
        "source": SourceName.SERP_JOBS,
        "posture": Posture.AMBER,
        "enabled": True,
        "signoff": True,
        "note": "Public SERP job-posting signals (licensed provider).",
    },
    {
        "source": SourceName.YELLOW_PAGES,
        "posture": Posture.AMBER,
        "enabled": False,
        "signoff": False,
        "note": "Gated: requires sign-off before enabling.",
    },
    {
        "source": SourceName.CLUTCH,
        "posture": Posture.AMBER,
        "enabled": False,
        "signoff": False,
        "note": "Gated: requires sign-off before enabling.",
    },
    {
        "source": SourceName.INDEED,
        "posture": Posture.RED,
        "enabled": False,
        "signoff": False,
        "note": "Gated (RED): disabled by default.",
    },
    {
        "source": SourceName.LINKEDIN,
        "posture": Posture.RED,
        "enabled": False,
        "signoff": False,
        "note": "No authenticated LinkedIn scraping — disabled.",
    },
]


def seed_demo(*, session: Session | None = None) -> dict:
    """Provision the demo workspace, run the pipeline, seed the campaign.

    Returns a summary dict with the achieved funnel distribution.
    """
    owns = session is None
    session = session or sync_session_factory()
    try:
        tenant = _upsert_tenant(session)
        user = _upsert_admin(session, tenant)
        _upsert_settings(session, tenant, user)
        _upsert_source_configs(session, tenant, user)
        job, ran = _upsert_job(session, tenant, user)
        _upsert_audit_log(session, tenant, user, job)
        session.commit()

        if ran:
            run_job_inline(job.id, session=session)
            session.commit()

        # Undo any prior demo-campaign side effects (suppressions/tombstones/
        # contact-status flips) so a re-seed reproduces the exact same funnel.
        _reset_campaign_side_effects(session, tenant, job)
        recompute_sales_ready_for_job(session, job)
        session.flush()

        _seed_campaign(session, tenant, user, job)
        # Re-materialize sales-ready + re-flush the sheet mirror so the
        # suppression tombstones and campaign rows land everywhere.
        recompute_sales_ready_for_job(session, job)
        recompute_and_persist_totals(session, job)
        run_sync(session, tenant.id)
        session.commit()

        totals = compute_totals(session, job)
        totals["tenant_id"] = str(tenant.id)
        totals["job_id"] = str(job.id)
        return totals
    finally:
        if owns:
            session.close()


# --------------------------------------------------------------------------- #
# Upserts (idempotent by fixed UUID)
# --------------------------------------------------------------------------- #


def _upsert_tenant(session: Session) -> Tenant:
    tenant = session.get(Tenant, DEMO_IDS["tenant"])
    if tenant is None:
        tenant = Tenant(id=DEMO_IDS["tenant"], name=DEMO_TENANT_NAME)
        session.add(tenant)
    else:
        tenant.name = DEMO_TENANT_NAME
    session.flush()
    return tenant


def _upsert_admin(session: Session, tenant: Tenant) -> User:
    user = session.get(User, DEMO_IDS["user"])
    if user is None:
        user = User(
            id=DEMO_IDS["user"],
            tenant_id=tenant.id,
            name="Demo Admin",
            email=DEMO_ADMIN_EMAIL,
            role=Role.ADMIN,
        )
        session.add(user)
    else:
        user.tenant_id = tenant.id
        user.email = DEMO_ADMIN_EMAIL
        user.role = Role.ADMIN
    session.flush()
    return user


def _upsert_settings(session: Session, tenant: Tenant, user: User) -> None:
    rules = session.get(ValidationRuleSet, DEMO_IDS["rules"])
    if rules is None:
        session.add(
            ValidationRuleSet(
                id=DEMO_IDS["rules"], tenant_id=tenant.id, rules=default_validation_rules()
            )
        )
    else:
        rules.rules = default_validation_rules()

    cs = session.get(CampaignSettings, DEMO_IDS["campaign_settings"])
    if cs is None:
        session.add(
            CampaignSettings(
                id=DEMO_IDS["campaign_settings"],
                tenant_id=tenant.id,
                send_limit_per_hour=100,
                send_limit_per_day=300,
            )
        )
    session.flush()


def _upsert_source_configs(session: Session, tenant: Tenant, user: User) -> None:
    existing = {
        c.source_name: c
        for c in session.scalars(
            select(DataSourceConfig).where(DataSourceConfig.tenant_id == tenant.id)
        ).all()
    }
    for spec in _SOURCE_CONFIGS:
        name = spec["source"].value
        cfg = existing.get(name)
        signoff_at = utcnow() if spec["signoff"] else None
        signoff_user = user.id if spec["signoff"] else None
        if cfg is None:
            session.add(
                DataSourceConfig(
                    tenant_id=tenant.id,
                    source_name=name,
                    enabled=spec["enabled"],
                    compliance_posture=spec["posture"].value,
                    access_method=AccessMethod.MOCK.value,
                    legal_note=spec["note"],
                    requires_signoff=spec["posture"] != Posture.GREEN,
                    signoff_user_id=signoff_user,
                    signoff_at=signoff_at,
                )
            )
        else:
            cfg.enabled = spec["enabled"]
            cfg.compliance_posture = spec["posture"].value
            cfg.access_method = AccessMethod.MOCK.value
            cfg.legal_note = spec["note"]
            cfg.requires_signoff = spec["posture"] != Posture.GREEN
            cfg.signoff_user_id = signoff_user
            cfg.signoff_at = signoff_at
    session.flush()


def _upsert_job(session: Session, tenant: Tenant, user: User) -> tuple[MiningJob, bool]:
    """Upsert the demo job. Returns (job, needs_pipeline_run?).

    The pipeline only runs when the job has no Company rows yet, so re-seeding a
    populated workspace is cheap and does not double-process.
    """
    job = session.get(MiningJob, DEMO_IDS["job"])
    if job is None:
        job = MiningJob(
            id=DEMO_IDS["job"],
            tenant_id=tenant.id,
            created_by=user.id,
            name=DEMO_JOB_NAME,
            status=JobStatus.QUEUED,
            **_JOB_SPEC,
        )
        session.add(job)
        session.flush()
        return job, True

    # Existing job: refresh spec fields; re-run only if it never produced rows.
    job.tenant_id = tenant.id
    job.created_by = user.id
    job.name = DEMO_JOB_NAME
    for field, value in _JOB_SPEC.items():
        setattr(job, field, value)
    session.flush()
    has_companies = session.scalar(
        select(func.count()).select_from(Company).where(Company.job_id == job.id)
    )
    if not has_companies:
        job.status = JobStatus.QUEUED
        job.progress_percent = 0
        return job, True
    return job, False


@dataclass(frozen=True)
class _AuditSpec:
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    before_json: dict | None = None
    after_json: dict | None = None


def _upsert_audit_log(session: Session, tenant: Tenant, user: User, job: MiningJob) -> None:
    """Seed a small audit trail so the Audit_Log tab/screen is populated."""
    entries = [
        _AuditSpec(
            id=DEMO_IDS["audit_job"],
            action="job.created",
            entity_type="mining_job",
            entity_id=str(job.id),
            after_json={"name": job.name, "city": job.city, "status": "queued"},
        ),
        _AuditSpec(
            id=DEMO_IDS["audit_signoff"],
            action="data_source.signed_off",
            entity_type="data_source_config",
            entity_id=SourceName.FACEBOOK_SIGNALS.value,
            before_json={"enabled": False, "signoff_at": None},
            after_json={"enabled": True, "posture": Posture.AMBER.value},
        ),
        _AuditSpec(
            id=DEMO_IDS["audit_campaign"],
            action="campaign.completed",
            entity_type="campaign",
            entity_id=str(DEMO_IDS["campaign"]),
            after_json={"status": CampaignStatus.COMPLETED.value},
        ),
    ]
    for e in entries:
        row = session.get(AuditLog, e.id)
        if row is None:
            session.add(
                AuditLog(
                    id=e.id,
                    tenant_id=tenant.id,
                    actor_user_id=user.id,
                    action=e.action,
                    entity_type=e.entity_type,
                    entity_id=e.entity_id,
                    before_json=e.before_json,
                    after_json=e.after_json,
                )
            )
        else:
            row.action = e.action
            row.entity_type = e.entity_type
            row.entity_id = e.entity_id
            row.before_json = e.before_json
            row.after_json = e.after_json
    session.flush()


def _reset_campaign_side_effects(session: Session, tenant: Tenant, job: MiningJob) -> None:
    """Roll back the demo campaign's suppression/tombstone effects (re-seed).

    The campaign hard-bounces a slice of the sales-ready set, which suppresses
    those addresses and tombstones their leads. On a re-seed we must undo that so
    the funnel returns to the pipeline's clean state before we re-apply it — else
    every re-seed would erode the sales-ready pool.
    """
    # 1. Restore contacts that the previous campaign flipped to SUPPRESSED back to
    #    their pipeline-decided validation status (from the latest ValidationCheck).
    from app.models import ValidationCheck

    suppressed_contacts = session.scalars(
        select(Contact).where(
            Contact.job_id == job.id,
            Contact.final_email_status == FinalEmailStatus.SUPPRESSED.value,
        )
    ).all()
    for contact in suppressed_contacts:
        latest = session.scalar(
            select(ValidationCheck)
            .where(ValidationCheck.contact_id == contact.id)
            .order_by(ValidationCheck.created_at.desc())
        )
        contact.final_email_status = (
            latest.final_status
            if latest and latest.final_status
            else FinalEmailStatus.VERIFIED.value
        )

    # 2. Drop the demo campaign's bounce-driven suppressions.
    session.execute(
        delete(Suppression).where(
            Suppression.tenant_id == tenant.id,
            Suppression.source == "bounce_parser",
        )
    )
    # 3. Un-tombstone leads so recompute can re-rank the full verified set.
    session.execute(
        update(SalesReadyLead)
        .where(SalesReadyLead.job_id == job.id, SalesReadyLead.tombstoned.is_(True))
        .values(tombstoned=False)
    )
    session.flush()


# --------------------------------------------------------------------------- #
# Synthetic completed campaign (spec §21 outreach metrics)
# --------------------------------------------------------------------------- #

# Spec §21 outreach targets: sent to the sales-ready set, 3.1% bounce, 38 replies.
_BOUNCE_RATE = 0.031
_REPLY_COUNT = 38
_OPEN_RATE = 0.52
_DELIVERED_LAG = 0.985  # of sent, minus bounces


def _seed_campaign(session: Session, tenant: Tenant, user: User, job: MiningJob) -> Campaign:
    """Build one COMPLETED campaign over the verified sales-ready leads.

    Deterministic: recipients and per-message outcomes are ordered by the lead
    rank and bucketed by index, so the numbers reproduce on every re-seed. Hard
    bounces create Suppression rows, which tombstone the matching sales-ready
    leads on the next recompute (criterion 11/25).
    """
    # Clean any prior campaign rows for this fixed campaign (idempotent re-seed).
    prior = session.get(Campaign, DEMO_IDS["campaign"])
    if prior is not None:
        session.execute(delete(EmailMessage).where(EmailMessage.campaign_id == prior.id))
        session.flush()

    template = session.get(EmailTemplate, DEMO_IDS["template"])
    subject = "Audit & tax support for {{Company}}"
    body = (
        "Hi {{FirstName}},\n\n"
        "I came across {{Company}} in {{City}} and wanted to introduce our "
        "audit and tax-filing practice. Would you be open to a short call?\n\n"
        "Best,\nDemo Admin"
    )
    if template is None:
        template = EmailTemplate(
            id=DEMO_IDS["template"],
            tenant_id=tenant.id,
            name="Audit & Tax Intro",
            subject=subject,
            body=body,
            created_by=user.id,
        )
        session.add(template)
    else:
        template.subject = subject
        template.body = body
    session.flush()

    launched = utcnow() - timedelta(days=2)
    campaign = session.get(Campaign, DEMO_IDS["campaign"])
    if campaign is None:
        campaign = Campaign(
            id=DEMO_IDS["campaign"],
            tenant_id=tenant.id,
            created_by=user.id,
            job_id=job.id,
            template_id=template.id,
            name="Ahmedabad CA Firms — Q3 Intro",
            subject_template=subject,
            body_template=body,
            from_account=DEMO_ADMIN_EMAIL,
            status=CampaignStatus.COMPLETED,
            launched_at=launched,
        )
        session.add(campaign)
    else:
        campaign.job_id = job.id
        campaign.template_id = template.id
        campaign.status = CampaignStatus.COMPLETED
        campaign.launched_at = launched
    session.flush()

    # Recipients: current verified, non-tombstoned sales-ready leads, ranked.
    leads = session.scalars(
        select(SalesReadyLead)
        .where(
            SalesReadyLead.tenant_id == tenant.id,
            SalesReadyLead.job_id == job.id,
            SalesReadyLead.tombstoned.is_(False),
            SalesReadyLead.validation_status == FinalEmailStatus.VERIFIED,
        )
        .order_by(SalesReadyLead.rank, SalesReadyLead.created_at)
    ).all()
    if not leads:
        return campaign

    n = len(leads)
    n_bounce = max(1, round(_BOUNCE_RATE * n))
    n_reply = min(_REPLY_COUNT, n - n_bounce)
    n_open = min(round(_OPEN_RATE * n), n - n_bounce)

    # Deterministic bucketing by position: last `n_bounce` bounce; the first
    # `n_reply` reply; the first `n_open` open. Delivered = sent - bounced.
    bounce_start = n - n_bounce
    for i, lead in enumerate(leads):
        bounced = i >= bounce_start
        replied = (not bounced) and i < n_reply
        opened = (not bounced) and i < n_open
        delivered = not bounced

        sent_at = launched + timedelta(minutes=i)
        msg = EmailMessage(
            campaign_id=campaign.id,
            contact_id=lead.contact_id,
            to_email=lead.email,
            subject=_render(subject, lead),
            body=_render(body, lead),
            gmail_message_id=f"demo-gmail-{campaign.id}-{i:04d}",
            status=_message_status(bounced, replied, opened, delivered),
            scheduled_at=launched,
            sent_at=sent_at,
            delivered_at=(sent_at + timedelta(seconds=20)) if delivered else None,
            opened_at=(sent_at + timedelta(hours=3)) if opened else None,
            replied_at=(sent_at + timedelta(hours=6)) if replied else None,
            bounced_at=(sent_at + timedelta(seconds=30)) if bounced else None,
        )
        session.add(msg)
        session.flush()

        if bounced:
            _record_bounce(session, tenant, lead, msg)
        if replied:
            session.add(
                ReplyEvent(
                    email_message_id=msg.id,
                    contact_id=lead.contact_id,
                    gmail_message_id=f"demo-reply-{i:04d}",
                    snippet="Thanks for reaching out — please send more details.",
                    detected_at=sent_at + timedelta(hours=6),
                )
            )
    session.flush()
    return campaign


def _message_status(bounced: bool, replied: bool, opened: bool, delivered: bool) -> str:
    if bounced:
        return MessageStatus.HARD_BOUNCE.value
    if replied:
        return MessageStatus.REPLIED.value
    if opened:
        return MessageStatus.OPENED.value
    if delivered:
        return MessageStatus.DELIVERED.value
    return MessageStatus.SENT.value


def _record_bounce(
    session: Session, tenant: Tenant, lead: SalesReadyLead, msg: EmailMessage
) -> None:
    """Log a hard bounce + permanent suppression (tombstones the lead later)."""
    session.add(
        BounceEvent(
            email_message_id=msg.id,
            contact_id=lead.contact_id,
            email=lead.email,
            smtp_status_code="550",
            bounce_type=BounceType.HARD.value,
            diagnostic_code="550 5.1.1 recipient rejected",
            reason="Mailbox does not exist (hard bounce).",
            raw_message_reference=msg.gmail_message_id,
            detected_at=(msg.sent_at or utcnow()) + timedelta(seconds=30),
        )
    )
    # Suppress the address so it can never re-enter sales-ready (criterion 11/25).
    already = session.scalar(
        select(Suppression.id).where(
            Suppression.tenant_id == tenant.id,
            func.lower(Suppression.email) == lead.email.lower(),
        )
    )
    if already is None:
        session.add(
            Suppression(
                tenant_id=tenant.id,
                email=lead.email,
                reason="Hard bounce during Ahmedabad CA intro campaign.",
                source="bounce_parser",
                permanent=True,
            )
        )
    # Mark the contact's owning validation as suppressed so downstream recompute
    # drops it from sales-ready.
    contact = session.get(Contact, lead.contact_id) if lead.contact_id else None
    if contact is not None:
        contact.final_email_status = FinalEmailStatus.SUPPRESSED.value
        contact.sales_ready = False
    session.flush()


def _render(template: str, lead: SalesReadyLead) -> str:
    first = (lead.contact_name or "there").split()[0]
    return (
        template.replace("{{FirstName}}", first)
        .replace("{{Company}}", lead.company_name or "your firm")
        .replace("{{City}}", lead.city or "Ahmedabad")
    )
