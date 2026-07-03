"""validation_jobs queue — run the six-stage email validation for one candidate.

``validate_email(email_candidate_id)`` runs all stages, writes the
ValidationCheck + Contact.final_email_status, enqueues the Email_Validation +
Contacts sheet upserts immediately, and triggers a sales-ready recompute for the
contact. In a fan-out it decrements the validation counter in a ``finally``.
"""

from __future__ import annotations

import uuid

from app.models import Contact, EmailCandidate, MiningJob
from app.pipeline import stages
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import finish_unit, worker_session

__all__ = ["validate_email"]


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
