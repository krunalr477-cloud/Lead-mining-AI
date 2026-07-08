"""validation_jobs queue — run the six-stage email validation for one candidate.

``validate_email(email_candidate_id)`` runs all stages, writes the
ValidationCheck + Contact.final_email_status, enqueues the Email_Validation +
Contacts sheet upserts immediately, and triggers a sales-ready recompute for the
contact. In a fan-out it decrements the validation counter in a ``finally``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.constants import FinalEmailStatus
from app.db import utcnow
from app.models import Contact, EmailCandidate, MiningJob, ValidationCheck
from app.pipeline import stages
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import finish_unit, worker_session

__all__ = ["validate_email", "retry_unknown_batch"]

#: Retry policy for emails that came back UNKNOWN (transient provider failure).
UNKNOWN_MAX_RETRIES = 3
UNKNOWN_RETRY_DELAY_HOURS = 6
UNKNOWN_RETRY_BATCH = 200


@app.task(name="app.workers.tasks.validation.validate_email", bind=True)
def validate_email(
    self, email_candidate_id: str, job_id: str | None = None, stage: str | None = None
) -> dict:
    ecid = uuid.UUID(str(email_candidate_id))
    result: dict = {"email_candidate_id": str(ecid)}
    jid: uuid.UUID | None = None
    try:
        with worker_session() as session:
            candidate = session.get(EmailCandidate, ecid)
            if candidate is None:
                return {"error": "candidate not found"}
            contact = session.get(Contact, candidate.contact_id)
            job = session.get(MiningJob, contact.job_id) if contact and contact.job_id else None
            if job is None and job_id:
                job = session.get(MiningJob, uuid.UUID(str(job_id)))
            if job is None:
                return {"error": "job not found"}
            jid = job.id
            check = stages.run_validation_for_candidate(session, get_redis(), job, candidate)
            result["final_status"] = check.final_status
            # Immediately mirror validation + contact rows to the sheet.
            stages._enqueue(session, job.tenant_id, "Email_Validation", str(check.id))
            stages.sync_contact_row(session, job.tenant_id, candidate.contact_id)
            # Recompute sales-ready (cheap; per-job recompute keeps ranks stable).
            stages.recompute_sales_ready_for_job(session, job)
        return result
    finally:
        if stage and jid is not None:
            finish_unit(jid, stage)


@app.task(name="app.workers.tasks.validation.retry_unknown_batch")
def retry_unknown_batch(
    max_retries: int = UNKNOWN_MAX_RETRIES,
    delay_hours: int = UNKNOWN_RETRY_DELAY_HOURS,
    batch_size: int = UNKNOWN_RETRY_BATCH,
) -> dict:
    """Re-validate emails stuck at UNKNOWN_RETRY (spec §P8). A retry runs only once
    its last attempt has aged past ``delay_hours`` and it is under ``max_retries``,
    so transient provider failures (429 storms, verifier hiccups) eventually
    resolve without hammering. Updates the existing check in place."""
    cutoff = utcnow() - timedelta(hours=delay_hours)
    retried = 0
    exhausted = 0
    with worker_session() as session:
        # Latest check per candidate is the one whose final_status the candidate
        # mirrors; select checks still marked UNKNOWN_RETRY and aged past cutoff.
        checks = session.scalars(
            select(ValidationCheck)
            .where(ValidationCheck.final_status == FinalEmailStatus.UNKNOWN_RETRY.value)
            .where(ValidationCheck.created_at <= cutoff)
            .order_by(ValidationCheck.created_at.asc())
            .limit(batch_size)
        ).all()
        for check in checks:
            if (check.retry_count or 0) >= max_retries:
                exhausted += 1
                continue
            candidate = session.get(EmailCandidate, check.email_candidate_id)
            if candidate is None:
                continue
            contact = session.get(Contact, candidate.contact_id)
            job = session.get(MiningJob, contact.job_id) if contact and contact.job_id else None
            if job is None:
                continue
            updated = stages.run_validation_for_candidate(
                session, get_redis(), job, candidate, prior_check=check
            )
            stages._enqueue(session, job.tenant_id, "Email_Validation", str(updated.id))
            stages.sync_contact_row(session, job.tenant_id, candidate.contact_id)
            stages.recompute_sales_ready_for_job(session, job)
            retried += 1
    return {"retried": retried, "exhausted": exhausted}
