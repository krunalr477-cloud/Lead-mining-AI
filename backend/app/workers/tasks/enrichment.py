"""enrichment_jobs queue — fill missing contact emails via the enrichment provider.

``enrich_contact(job_id, contact_id, stage)`` enriches one contact; in a fan-out
it decrements the enrichment counter in a ``finally``.
"""

from __future__ import annotations

import uuid

from app.models import Contact, MiningJob
from app.pipeline import stages
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import finish_unit, worker_session

__all__ = ["enrich_contact"]


@app.task(name="app.workers.tasks.enrichment.enrich_contact", bind=True)
def enrich_contact(self, job_id: str, contact_id: str, stage: str | None = None) -> dict:
    jid = uuid.UUID(str(job_id))
    cid = uuid.UUID(str(contact_id))
    result: dict = {"contact_id": str(cid)}
    try:
        with worker_session() as session:
            job = session.get(MiningJob, jid)
            contact = session.get(Contact, cid)
            if job is None or contact is None:
                return {"error": "job or contact not found"}
            result.update(stages.run_enrichment(session, get_redis(), job, contact))
        return result
    finally:
        if stage:
            finish_unit(jid, stage)
