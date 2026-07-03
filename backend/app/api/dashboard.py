"""Dashboard + queue-health endpoints (spec §15 / §19).

GET /dashboard/summary               all §15 metrics
GET /dashboard/funnel                Companies->Contacts->Emails->Verified->SalesReady->Sent->Replies
GET /dashboard/source-performance    per-source discovery + compliance rollup
GET /dashboard/campaign-performance  per-campaign send/open/click/reply/bounce
GET /queues/health                   Redis queue depths for the 12 queues
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.constants import (
    QUEUES,
    FinalEmailStatus,
    JobStatus,
    SourceRunStatus,
    StageStatus,
)
from app.deps import SessionDep, TenantId, require
from app.models import (
    APIUsage,
    Campaign,
    Company,
    Contact,
    EmailCandidate,
    EmailMessage,
    MiningJob,
    ReplyEvent,
    SalesReadyLead,
    SourceRun,
    ValidationCheck,
)

router = APIRouter(tags=["dashboard"])

ReadActor = Annotated[Contact, Depends(require("dashboard:read"))]

_REVIEW_STATES = {
    FinalEmailStatus.CATCH_ALL_REVIEW.value,
    FinalEmailStatus.RISK_REVIEW.value,
    FinalEmailStatus.LLM_LOW_CONFIDENCE.value,
    FinalEmailStatus.UNKNOWN_RETRY.value,
}
_INVALID_STATES = {
    FinalEmailStatus.INVALID_SYNTAX.value,
    FinalEmailStatus.DISPOSABLE_REJECTED.value,
    FinalEmailStatus.ROLE_BASED_REJECTED.value,
    FinalEmailStatus.MX_FAILED.value,
    FinalEmailStatus.PROVIDER_INVALID.value,
    FinalEmailStatus.SUPPRESSED.value,
}


async def _count(session, stmt) -> int:
    return int(await session.scalar(stmt) or 0)


@router.get("/dashboard/summary")
async def dashboard_summary(_actor: ReadActor, tenant_id: TenantId, session: SessionDep) -> dict:
    companies = await _count(
        session, select(func.count()).select_from(Company).where(Company.tenant_id == tenant_id)
    )
    contacts = await _count(
        session, select(func.count()).select_from(Contact).where(Contact.tenant_id == tenant_id)
    )
    emails = await _count(
        session,
        select(func.count())
        .select_from(EmailCandidate)
        .join(Contact, EmailCandidate.contact_id == Contact.id)
        .where(Contact.tenant_id == tenant_id),
    )

    status_counts: dict[str | None, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Contact.final_email_status, func.count())
                .where(Contact.tenant_id == tenant_id)
                .group_by(Contact.final_email_status)
            )
        ).all()
    }
    verified = status_counts.get(FinalEmailStatus.VERIFIED.value, 0)
    invalid = sum(n for s, n in status_counts.items() if s in _INVALID_STATES)
    review = sum(n for s, n in status_counts.items() if s in _REVIEW_STATES)

    sales_ready = await _count(
        session,
        select(func.count())
        .select_from(SalesReadyLead)
        .where(SalesReadyLead.tenant_id == tenant_id, SalesReadyLead.tombstoned.is_(False)),
    )

    # Campaign message rollup.
    msg_rows = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count(EmailMessage.sent_at).label("sent"),
                func.count(EmailMessage.delivered_at).label("delivered"),
                func.count(EmailMessage.opened_at).label("opened"),
                func.count(EmailMessage.clicked_at).label("clicked"),
                func.count(EmailMessage.replied_at).label("replied"),
                func.count(EmailMessage.bounced_at).label("bounced"),
            )
            .select_from(EmailMessage)
            .join(Campaign, EmailMessage.campaign_id == Campaign.id)
            .where(Campaign.tenant_id == tenant_id)
        )
    ).one()
    sent = msg_rows.sent or 0
    delivered = msg_rows.delivered or 0

    def _rate(numer: int, denom: int) -> float:
        return round(100.0 * numer / denom, 2) if denom else 0.0

    active_jobs = await _count(
        session,
        select(func.count())
        .select_from(MiningJob)
        .where(
            MiningJob.tenant_id == tenant_id,
            MiningJob.status.in_([JobStatus.RUNNING, JobStatus.QUEUED]),
        ),
    )
    failed_jobs = await _count(
        session,
        select(func.count())
        .select_from(MiningJob)
        .where(MiningJob.tenant_id == tenant_id, MiningJob.status == JobStatus.FAILED),
    )

    api_cost = await session.scalar(
        select(func.coalesce(func.sum(APIUsage.estimated_cost), 0)).where(
            APIUsage.tenant_id == tenant_id
        )
    )
    api_requests = await _count(
        session,
        select(func.coalesce(func.sum(APIUsage.request_count), 0)).where(
            APIUsage.tenant_id == tenant_id
        ),
    )

    return {
        "companies_mined": companies,
        "contacts_found": contacts,
        "emails_found": emails,
        "verified_emails": verified,
        "invalid_emails": invalid,
        "review_emails": review,
        "sales_ready_leads": sales_ready,
        "emails_sent": sent,
        "delivered": delivered,
        "open_rate": _rate(msg_rows.opened or 0, delivered or sent),
        "click_rate": _rate(msg_rows.clicked or 0, delivered or sent),
        "reply_rate": _rate(msg_rows.replied or 0, sent),
        "bounce_rate": _rate(msg_rows.bounced or 0, sent),
        "active_jobs": active_jobs,
        "failed_jobs": failed_jobs,
        "api_requests": api_requests,
        "estimated_api_cost_usd": float(api_cost or 0),
        "validation_rejection_reasons": await _rejection_reasons(session, tenant_id),
    }


async def _rejection_reasons(session, tenant_id) -> dict:
    """Per-stage rejection counts across all validation checks (spec §15)."""
    rows = (
        await session.execute(
            select(
                func.count().filter(ValidationCheck.syntax_status == StageStatus.FAIL),
                func.count().filter(ValidationCheck.disposable_status == StageStatus.FAIL),
                func.count().filter(ValidationCheck.role_based_status == StageStatus.FAIL),
                func.count().filter(ValidationCheck.mx_status == StageStatus.FAIL),
                func.count().filter(
                    ValidationCheck.final_status == FinalEmailStatus.LLM_LOW_CONFIDENCE
                ),
                func.count().filter(
                    ValidationCheck.final_status == FinalEmailStatus.PROVIDER_INVALID
                ),
            )
            .select_from(ValidationCheck)
            .join(Contact, ValidationCheck.contact_id == Contact.id)
            .where(Contact.tenant_id == tenant_id)
        )
    ).one()
    return {
        "syntax": rows[0] or 0,
        "disposable": rows[1] or 0,
        "role_based": rows[2] or 0,
        "mx": rows[3] or 0,
        "llm": rows[4] or 0,
        "provider": rows[5] or 0,
    }


@router.get("/dashboard/funnel")
async def dashboard_funnel(_actor: ReadActor, tenant_id: TenantId, session: SessionDep) -> dict:
    companies = await _count(
        session, select(func.count()).select_from(Company).where(Company.tenant_id == tenant_id)
    )
    contacts = await _count(
        session, select(func.count()).select_from(Contact).where(Contact.tenant_id == tenant_id)
    )
    emails = await _count(
        session,
        select(func.count())
        .select_from(EmailCandidate)
        .join(Contact, EmailCandidate.contact_id == Contact.id)
        .where(Contact.tenant_id == tenant_id),
    )
    verified = await _count(
        session,
        select(func.count())
        .select_from(Contact)
        .where(
            Contact.tenant_id == tenant_id,
            Contact.final_email_status == FinalEmailStatus.VERIFIED,
        ),
    )
    sales_ready = await _count(
        session,
        select(func.count())
        .select_from(SalesReadyLead)
        .where(SalesReadyLead.tenant_id == tenant_id, SalesReadyLead.tombstoned.is_(False)),
    )
    sent = await _count(
        session,
        select(func.count())
        .select_from(EmailMessage)
        .join(Campaign, EmailMessage.campaign_id == Campaign.id)
        .where(Campaign.tenant_id == tenant_id, EmailMessage.sent_at.is_not(None)),
    )
    replies = await _count(
        session,
        select(func.count())
        .select_from(ReplyEvent)
        .join(EmailMessage, ReplyEvent.email_message_id == EmailMessage.id)
        .join(Campaign, EmailMessage.campaign_id == Campaign.id)
        .where(Campaign.tenant_id == tenant_id),
    )
    return {
        "stages": [
            {"stage": "Companies", "count": companies},
            {"stage": "Contacts", "count": contacts},
            {"stage": "Emails", "count": emails},
            {"stage": "Verified", "count": verified},
            {"stage": "Sales Ready", "count": sales_ready},
            {"stage": "Sent", "count": sent},
            {"stage": "Replies", "count": replies},
        ]
    }


@router.get("/dashboard/source-performance")
async def source_performance(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> list[dict]:
    rows = (
        await session.execute(
            select(
                SourceRun.source_name,
                SourceRun.compliance_posture,
                func.count().label("runs"),
                func.coalesce(func.sum(SourceRun.records_found), 0),
                func.coalesce(func.sum(SourceRun.records_imported), 0),
                func.count().filter(SourceRun.status == SourceRunStatus.SKIPPED),
                func.count().filter(SourceRun.status == SourceRunStatus.FAILED),
            )
            .select_from(SourceRun)
            .join(MiningJob, SourceRun.job_id == MiningJob.id)
            .where(MiningJob.tenant_id == tenant_id)
            .group_by(SourceRun.source_name, SourceRun.compliance_posture)
            .order_by(SourceRun.source_name)
        )
    ).all()
    return [
        {
            "source_name": r[0],
            "compliance_posture": r[1],
            "runs": r[2],
            "records_found": int(r[3]),
            "records_imported": int(r[4]),
            "skipped_runs": r[5],
            "failed_runs": r[6],
        }
        for r in rows
    ]


@router.get("/dashboard/campaign-performance")
async def campaign_performance(
    _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> list[dict]:
    campaigns = list(
        await session.scalars(
            select(Campaign).where(Campaign.tenant_id == tenant_id).order_by(Campaign.created_at)
        )
    )
    out = []
    for c in campaigns:
        row = (
            await session.execute(
                select(
                    func.count(),
                    func.count(EmailMessage.sent_at),
                    func.count(EmailMessage.delivered_at),
                    func.count(EmailMessage.opened_at),
                    func.count(EmailMessage.clicked_at),
                    func.count(EmailMessage.replied_at),
                    func.count(EmailMessage.bounced_at),
                )
                .select_from(EmailMessage)
                .where(EmailMessage.campaign_id == c.id)
            )
        ).one()
        out.append(
            {
                "campaign_id": str(c.id),
                "name": c.name,
                "status": c.status,
                "recipients": row[0],
                "sent": row[1],
                "delivered": row[2],
                "opened": row[3],
                "clicked": row[4],
                "replied": row[5],
                "bounced": row[6],
            }
        )
    return out


@router.get("/queues/health")
async def queue_health(_actor: ReadActor) -> dict:
    """Redis list-length per queue (Celery default transport uses a Redis list)."""
    from app.workers.rate_limit import get_redis

    client = get_redis()
    depths: dict[str, int] = {}
    for queue in QUEUES:
        try:
            depths[queue] = int(client.llen(queue))  # type: ignore[arg-type]
        except Exception:
            depths[queue] = -1
    return {"queues": depths, "total_pending": sum(v for v in depths.values() if v > 0)}
