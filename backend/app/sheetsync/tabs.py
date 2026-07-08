"""Declarative tab specifications for the 12 sheet tabs (spec §5).

Each :class:`TabSpec` pairs an exact column list with a ``source`` callable that
maps DB rows to ``{column: value}`` dicts. The engine consumes these specs to
setup headers, diff rows, and push system-owned columns only.

Column lists match spec §5 tab-for-tab. ``key_column`` is the stable row id used
to append/update. ``editable_columns`` are sales-owned and never pushed by the
engine (they are pulled from the sheet):
- Contacts:          owner, sales_notes, next_action
- Sales_Ready_Leads: owner, sales_notes, next_action
All other tabs are fully backend-owned (no editable columns).

``status_columns`` maps a column name to the status-rule key used for
conditional-format coloring (see :data:`app.sheetsync.engine.STATUS_COLORS`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants import FinalEmailStatus
from app.models import (
    AuditLog,
    BounceEvent,
    Campaign,
    Company,
    Contact,
    DataSourceAuditEvent,
    EmailMessage,
    MiningJob,
    SalesReadyLead,
    Suppression,
    ValidationCheck,
)

# Row dict: column name -> serializable scalar (str/int/float/bool/None).
RowDict = dict[str, Any]
SourceFn = Callable[[Session, UUID], list[RowDict]]

__all__ = ["TABS", "TABS_BY_NAME", "TabSpec", "scalarize"]


def scalarize(value: Any) -> Any:
    """Coerce a DB value to a sheet-cell scalar (stable across flushes).

    Idempotency depends on this being deterministic: the same DB value must
    always hash to the same cell string, so lists/UUIDs/datetimes/Decimals get a
    canonical rendering.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        # ISO-8601; drop microseconds for stable, human-readable cells.
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, Decimal):
        # Preserve whole numbers as ints so counts/review-counts render "14",
        # not "14.0"; keep true fractionals (ratings like 4.6) as floats.
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(scalarize(v) for v in value if v is not None)
    return value


@dataclass(frozen=True)
class TabSpec:
    """One sheet tab: its columns, key, editable set, colors, and DB source."""

    name: str
    columns: Sequence[str]
    key_column: str
    source: SourceFn
    editable_columns: tuple[str, ...] = ()
    status_columns: dict[str, str] = field(default_factory=dict)

    def system_columns(self) -> list[str]:
        """Columns the backend owns and is allowed to write (all non-editable)."""
        editable = set(self.editable_columns)
        return [c for c in self.columns if c not in editable]

    def project(self, row: RowDict) -> RowDict:
        """Return a full row dict covering every column (missing -> "")."""
        return {c: scalarize(row.get(c, "")) for c in self.columns}

    def content_row(self, row: RowDict) -> RowDict:
        """System-owned projection used for content hashing / diffing.

        Editable columns are excluded so a sales edit in the DB source never
        counts as a change the engine would push.
        """
        return {c: scalarize(row.get(c, "")) for c in self.system_columns()}


# --------------------------------------------------------------------------- #
# Source callables. Each returns list[RowDict] keyed by the tab's key_column.  #
# All read via the sync Session (workers/scripts) scoped to one tenant.        #
# --------------------------------------------------------------------------- #


def _readme_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    """README is static documentation, not DB-backed."""
    rows: list[RowDict] = []
    for tab in TABS:
        if tab.name == "README":
            continue
        rows.append(
            {
                "tab": tab.name,
                "key_column": tab.key_column,
                "editable_columns": ", ".join(tab.editable_columns) or "(none)",
                "columns": ", ".join(tab.columns),
                "notes": _README_NOTES.get(tab.name, ""),
            }
        )
    return rows


_README_NOTES = {
    "Mining_Jobs": "One row per mining job. Backend-owned.",
    "Companies": "Deduplicated companies. Backend-owned.",
    "Contacts": "Discovered contacts. Sales may edit owner/sales_notes/next_action.",
    "Email_Validation": "Per-email validation results. Backend-owned.",
    "Sales_Ready_Leads": (
        "Clean output. VERIFIED + non-suppressed only. "
        "Sales may edit owner/sales_notes/next_action."
    ),
    "Outreach_Queue": "Send pipeline state. Backend-owned.",
    "Campaigns": "Campaign rollups. Backend-owned.",
    "Bounce_Log": "Bounce events. Backend-owned.",
    "Suppression_List": "Suppressed emails/domains. Backend-owned.",
    "Data_Source_Audit": "Per-source compliance audit. Backend-owned.",
    "Audit_Log": "Who changed what. Backend-owned.",
}


def _mining_jobs_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    jobs = session.scalars(
        select(MiningJob).where(MiningJob.tenant_id == tenant_id).order_by(MiningJob.created_at)
    ).all()
    rows: list[RowDict] = []
    for j in jobs:
        totals = j.totals_json or {}
        size = ""
        if j.company_size_min is not None or j.company_size_max is not None:
            size = f"{j.company_size_min or ''}-{j.company_size_max or ''}"
        rows.append(
            {
                "job_id": j.id,
                "job_name": j.name,
                "created_by": j.created_by,
                "created_at": j.created_at,
                "status": j.status,
                "company_type": j.company_type,
                "services": j.services,
                "country": j.country,
                "state": j.state,
                "city": j.city,
                "zipcode": j.zipcode,
                "latitude": j.latitude,
                "longitude": j.longitude,
                "radius_km": j.radius_km,
                "company_size": size,
                "selected_sources": j.selected_sources,
                "total_companies": totals.get("total_companies", 0),
                "total_contacts": totals.get("total_contacts", 0),
                "verified_emails": totals.get("verified_emails", 0),
                "invalid_emails": totals.get("invalid_emails", 0),
                "review_emails": totals.get("review_emails", 0),
                "sales_ready_count": totals.get("sales_ready_count", 0),
                "campaign_id": totals.get("campaign_id", ""),
                "notes": j.notes,
            }
        )
    return rows


def _companies_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    companies = session.scalars(
        select(Company).where(Company.tenant_id == tenant_id).order_by(Company.created_at)
    ).all()
    rows: list[RowDict] = []
    for c in companies:
        source_names = sorted({s.source_name for s in c.sources})
        source_urls = [s.source_url for s in c.sources if s.source_url]
        rows.append(
            {
                "company_id": c.id,
                "job_id": c.job_id,
                "company_name": c.canonical_name,
                "website": c.website,
                "domain": c.domain,
                "phone": c.phone,
                "address": c.address,
                "city": c.city,
                "state": c.state,
                "country": c.country,
                "postal_code": c.postal_code,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "industry": c.industry,
                "services": c.services,
                "company_size": c.company_size,
                "google_rating": c.google_rating,
                "google_reviews": c.google_reviews,
                "source_names": source_names or c.source_urls,
                "source_urls": source_urls or c.source_urls,
                "website_status": c.website_status,
                "hiring_signal_status": c.hiring_signal_status,
                "facebook_page_url": c.facebook_page_url,
                "last_refreshed_at": c.last_refreshed_at,
                "compliance_posture": c.compliance_posture,
                "dedupe_status": c.dedupe_status,
            }
        )
    return rows


def _contacts_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    contacts = session.scalars(
        select(Contact).where(Contact.tenant_id == tenant_id).order_by(Contact.created_at)
    ).all()
    rows: list[RowDict] = []
    for ct in contacts:
        rows.append(
            {
                "contact_id": ct.id,
                "company_id": ct.company_id,
                "job_id": ct.job_id,
                "contact_name": ct.full_name,
                "first_name": ct.first_name,
                "last_name": ct.last_name,
                "designation": ct.designation,
                "department": ct.department,
                "seniority": ct.seniority,
                "role_category": ct.role_category,
                "email": ct.email,
                "phone": ct.phone,
                "linkedin_url": ct.linkedin_url,
                "facebook_url": ct.facebook_url,
                "source_page": ct.source_page,
                "source_type": ct.source_type,
                "confidence_score": ct.confidence_score,
                "primary_contact": ct.primary_contact,
                "enrichment_provider": ct.enrichment_provider,
                "enrichment_status": ct.enrichment_status,
                "last_verified_at": ct.last_verified_at,
                "final_email_status": ct.final_email_status,
                "sales_ready": ct.sales_ready,
                # Editable — engine never pushes these; sheet is source of truth.
                "owner": ct.owner_user_id,
                "sales_notes": ct.notes,
                "next_action": "",
            }
        )
    return rows


def _email_validation_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    # ValidationCheck has no tenant_id; scope via its Contact.
    checks = session.scalars(
        select(ValidationCheck)
        .join(Contact, ValidationCheck.contact_id == Contact.id)
        .where(Contact.tenant_id == tenant_id)
        .order_by(ValidationCheck.created_at)
        .options(selectinload(ValidationCheck.email_candidate))
    ).all()
    rows: list[RowDict] = []
    for v in checks:
        email = v.email_candidate.email if v.email_candidate else ""
        rows.append(
            {
                "validation_id": v.id,
                "contact_id": v.contact_id,
                "company_id": v.company_id,
                "email": email,
                "syntax_status": v.syntax_status,
                "disposable_status": v.disposable_status,
                "role_based_status": v.role_based_status,
                "mx_status": v.mx_status,
                "llm_score": v.llm_score,
                "llm_reason": v.llm_reason,
                "millionverifier_status": v.millionverifier_status,
                "final_status": v.final_status,
                "final_reason": v.final_reason,
                "verified_at": v.verified_at,
                "retry_count": v.retry_count,
                "raw_provider_result": v.raw_result_json,
            }
        )
    return rows


def _sales_ready_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    """Only VERIFIED, non-tombstoned leads reach the sales team (spec §5 line 464).

    Tombstoning captures later suppression/hard-bounce; ``validation_status``
    must be VERIFIED, so invalid/role-based/disposable/unknown never appear.
    """
    leads = session.scalars(
        select(SalesReadyLead)
        .where(
            SalesReadyLead.tenant_id == tenant_id,
            SalesReadyLead.tombstoned.is_(False),
            SalesReadyLead.validation_status == FinalEmailStatus.VERIFIED,
        )
        .order_by(SalesReadyLead.rank, SalesReadyLead.created_at)
    ).all()
    rows: list[RowDict] = []
    for lead in leads:
        rows.append(
            {
                "sales_lead_id": lead.id,
                "job_id": lead.job_id,
                "company_name": lead.company_name,
                "website": lead.website,
                "city": lead.city,
                "state": lead.state,
                "country": lead.country,
                "contact_name": lead.contact_name,
                "designation": lead.designation,
                "email": lead.email,
                "phone": lead.phone,
                "services": lead.services,
                "source_summary": lead.source_summary,
                "validation_status": lead.validation_status,
                "confidence_score": lead.confidence_score,
                "last_verified_at": lead.last_verified_at,
                "campaign_status": lead.campaign_status,
                # Editable — engine never pushes these.
                "owner": lead.owner,
                "next_action": lead.next_action,
                "sales_notes": lead.sales_notes,
            }
        )
    return rows


def _outreach_queue_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    msgs = session.scalars(
        select(EmailMessage)
        .join(Campaign, EmailMessage.campaign_id == Campaign.id)
        .where(Campaign.tenant_id == tenant_id)
        .order_by(EmailMessage.created_at)
    ).all()
    rows: list[RowDict] = []
    for m in msgs:
        bounce_status = ""
        if m.bounced_at is not None:
            bounce_status = "bounced"
        rows.append(
            {
                "queue_id": m.id,
                "campaign_id": m.campaign_id,
                "contact_id": m.contact_id,
                "email": m.to_email,
                "company_name": "",
                "subject": m.subject,
                "send_status": m.status,
                "scheduled_at": m.scheduled_at,
                "sent_at": m.sent_at,
                "gmail_message_id": m.gmail_message_id,
                "opened_at": m.opened_at,
                "clicked_at": m.clicked_at,
                "replied_at": m.replied_at,
                "bounce_status": bounce_status,
                "suppression_status": "",
            }
        )
    return rows


def _campaigns_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    campaigns = session.scalars(
        select(Campaign)
        .where(Campaign.tenant_id == tenant_id)
        .order_by(Campaign.created_at)
        .options(selectinload(Campaign.messages))
    ).all()
    rows: list[RowDict] = []
    for c in campaigns:
        msgs = c.messages
        sent = sum(1 for m in msgs if m.sent_at is not None)
        delivered = sum(1 for m in msgs if m.delivered_at is not None)
        opened = sum(1 for m in msgs if m.opened_at is not None)
        clicked = sum(1 for m in msgs if m.clicked_at is not None)
        replied = sum(1 for m in msgs if m.replied_at is not None)
        bounced = sum(1 for m in msgs if m.bounced_at is not None)
        rows.append(
            {
                "campaign_id": c.id,
                "campaign_name": c.name,
                "job_id": c.job_id,
                "from_account": c.from_account,
                "template_id": c.template_id,
                "recipient_count": len(msgs),
                "sent_count": sent,
                "delivered_count": delivered,
                "open_count": opened,
                "click_count": clicked,
                "reply_count": replied,
                "bounce_count": bounced,
                "status": c.status,
                "started_at": c.launched_at,
                "completed_at": c.updated_at if c.status == "completed" else None,
            }
        )
    return rows


def _bounce_log_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    bounces = session.scalars(
        select(BounceEvent)
        .join(EmailMessage, BounceEvent.email_message_id == EmailMessage.id)
        .join(Campaign, EmailMessage.campaign_id == Campaign.id)
        .where(Campaign.tenant_id == tenant_id)
        .order_by(BounceEvent.detected_at)
        .options(selectinload(BounceEvent.email_message))
    ).all()
    rows: list[RowDict] = []
    for b in bounces:
        gmail_id = b.email_message.gmail_message_id if b.email_message else ""
        campaign_id = b.email_message.campaign_id if b.email_message else ""
        action = "suppressed" if b.bounce_type == "hard" else "flagged"
        rows.append(
            {
                "bounce_id": b.id,
                "campaign_id": campaign_id,
                "contact_id": b.contact_id,
                "email": b.email,
                "gmail_message_id": gmail_id,
                "smtp_status_code": b.smtp_status_code,
                "bounce_type": b.bounce_type,
                "bounce_reason": b.reason,
                "detected_at": b.detected_at,
                "action_taken": action,
            }
        )
    return rows


def _suppression_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    supps = session.scalars(
        select(Suppression)
        .where(Suppression.tenant_id == tenant_id)
        .order_by(Suppression.created_at)
    ).all()
    rows: list[RowDict] = []
    for s in supps:
        # Key must be stable and non-empty even for domain-only suppressions.
        key = s.email or (f"@{s.domain}" if s.domain else str(s.id))
        rows.append(
            {
                "email": key,
                "domain": s.domain,
                "reason": s.reason,
                "source": s.source,
                "suppressed_at": s.created_at,
                "permanent": s.permanent,
            }
        )
    return rows


def _data_source_audit_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    events = session.scalars(
        select(DataSourceAuditEvent)
        .where(DataSourceAuditEvent.tenant_id == tenant_id)
        .order_by(DataSourceAuditEvent.created_at)
    ).all()
    rows: list[RowDict] = []
    for e in events:
        rows.append(
            {
                "event_id": e.id,
                "job_id": e.job_id,
                "source_name": e.source_name,
                "source_type": e.source_type,
                "access_method": e.access_method,
                "compliance_posture": e.compliance_posture,
                "url_or_endpoint": e.url_or_endpoint,
                "status": e.status,
                "records_found": e.records_found,
                "error_message": e.error_message,
                "created_at": e.created_at,
            }
        )
    return rows


def _audit_log_source(session: Session, tenant_id: UUID) -> list[RowDict]:
    logs = session.scalars(
        select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.created_at)
    ).all()
    rows: list[RowDict] = []
    for a in logs:
        rows.append(
            {
                "audit_id": a.id,
                "actor": a.actor_user_id,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "before_value": a.before_json,
                "after_value": a.after_json,
                "created_at": a.created_at,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# The 12 tabs, in sheet order (spec §5). Column lists are exact.               #
# --------------------------------------------------------------------------- #

_EDITABLE = ("owner", "sales_notes", "next_action")

TABS: list[TabSpec] = [
    TabSpec(
        name="README",
        columns=["tab", "key_column", "editable_columns", "columns", "notes"],
        key_column="tab",
        source=_readme_source,
    ),
    TabSpec(
        name="Mining_Jobs",
        columns=[
            "job_id",
            "job_name",
            "created_by",
            "created_at",
            "status",
            "company_type",
            "services",
            "country",
            "state",
            "city",
            "zipcode",
            "latitude",
            "longitude",
            "radius_km",
            "company_size",
            "selected_sources",
            "total_companies",
            "total_contacts",
            "verified_emails",
            "invalid_emails",
            "review_emails",
            "sales_ready_count",
            "campaign_id",
            "notes",
        ],
        key_column="job_id",
        source=_mining_jobs_source,
        status_columns={"status": "job_status"},
    ),
    TabSpec(
        name="Companies",
        columns=[
            "company_id",
            "job_id",
            "company_name",
            "website",
            "domain",
            "phone",
            "address",
            "city",
            "state",
            "country",
            "postal_code",
            "latitude",
            "longitude",
            "industry",
            "services",
            "company_size",
            "google_rating",
            "google_reviews",
            "source_names",
            "source_urls",
            "website_status",
            "hiring_signal_status",
            "facebook_page_url",
            "last_refreshed_at",
            "compliance_posture",
            "dedupe_status",
        ],
        key_column="company_id",
        source=_companies_source,
    ),
    TabSpec(
        name="Contacts",
        columns=[
            "contact_id",
            "company_id",
            "job_id",
            "contact_name",
            "first_name",
            "last_name",
            "designation",
            "department",
            "seniority",
            "role_category",
            "email",
            "phone",
            "linkedin_url",
            "facebook_url",
            "source_page",
            "source_type",
            "confidence_score",
            "primary_contact",
            "enrichment_provider",
            "enrichment_status",
            "last_verified_at",
            "final_email_status",
            "sales_ready",
            "owner",
            "sales_notes",
            "next_action",
        ],
        key_column="contact_id",
        source=_contacts_source,
        editable_columns=_EDITABLE,
        status_columns={"final_email_status": "email_status"},
    ),
    TabSpec(
        name="Email_Validation",
        columns=[
            "validation_id",
            "contact_id",
            "company_id",
            "email",
            "syntax_status",
            "disposable_status",
            "role_based_status",
            "mx_status",
            "llm_score",
            "llm_reason",
            "millionverifier_status",
            "final_status",
            "final_reason",
            "verified_at",
            "retry_count",
            "raw_provider_result",
        ],
        key_column="validation_id",
        source=_email_validation_source,
        status_columns={
            "final_status": "email_status",
            "millionverifier_status": "mv_status",
        },
    ),
    TabSpec(
        name="Sales_Ready_Leads",
        columns=[
            "sales_lead_id",
            "job_id",
            "company_name",
            "website",
            "city",
            "state",
            "country",
            "contact_name",
            "designation",
            "email",
            "phone",
            "services",
            "source_summary",
            "validation_status",
            "confidence_score",
            "last_verified_at",
            "campaign_status",
            "owner",
            "next_action",
            "sales_notes",
        ],
        key_column="sales_lead_id",
        source=_sales_ready_source,
        editable_columns=_EDITABLE,
        status_columns={
            "validation_status": "email_status",
            "campaign_status": "campaign_status",
        },
    ),
    TabSpec(
        name="Outreach_Queue",
        columns=[
            "queue_id",
            "campaign_id",
            "contact_id",
            "email",
            "company_name",
            "subject",
            "send_status",
            "scheduled_at",
            "sent_at",
            "gmail_message_id",
            "opened_at",
            "clicked_at",
            "replied_at",
            "bounce_status",
            "suppression_status",
        ],
        key_column="queue_id",
        source=_outreach_queue_source,
        status_columns={"send_status": "send_status", "bounce_status": "bounce_status"},
    ),
    TabSpec(
        name="Campaigns",
        columns=[
            "campaign_id",
            "campaign_name",
            "job_id",
            "from_account",
            "template_id",
            "recipient_count",
            "sent_count",
            "delivered_count",
            "open_count",
            "click_count",
            "reply_count",
            "bounce_count",
            "status",
            "started_at",
            "completed_at",
        ],
        key_column="campaign_id",
        source=_campaigns_source,
        status_columns={"status": "campaign_status"},
    ),
    TabSpec(
        name="Bounce_Log",
        columns=[
            "bounce_id",
            "campaign_id",
            "contact_id",
            "email",
            "gmail_message_id",
            "smtp_status_code",
            "bounce_type",
            "bounce_reason",
            "detected_at",
            "action_taken",
        ],
        key_column="bounce_id",
        source=_bounce_log_source,
        status_columns={"bounce_type": "bounce_status"},
    ),
    TabSpec(
        name="Suppression_List",
        columns=["email", "domain", "reason", "source", "suppressed_at", "permanent"],
        key_column="email",
        source=_suppression_source,
    ),
    TabSpec(
        name="Data_Source_Audit",
        columns=[
            "event_id",
            "job_id",
            "source_name",
            "source_type",
            "access_method",
            "compliance_posture",
            "url_or_endpoint",
            "status",
            "records_found",
            "error_message",
            "created_at",
        ],
        key_column="event_id",
        source=_data_source_audit_source,
        status_columns={"status": "source_status"},
    ),
    TabSpec(
        name="Audit_Log",
        columns=[
            "audit_id",
            "actor",
            "action",
            "entity_type",
            "entity_id",
            "before_value",
            "after_value",
            "created_at",
        ],
        key_column="audit_id",
        source=_audit_log_source,
    ),
]

TABS_BY_NAME: dict[str, TabSpec] = {t.name: t for t in TABS}
