"""audit_jobs queue — audit-log writes, API-usage records, sales-ready recompute.

Small side-effect tasks that don't belong to a data-source queue:
- ``write_audit`` appends an AuditLog row (who changed what).
- ``record_api_usage`` upserts an APIUsage row (metered provider cost).
- ``recompute_sales_ready`` materializes/tombstones SalesReadyLead for a job.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.models import APIUsage, AuditLog, MiningJob
from app.pipeline import stages
from app.workers.celery_app import app
from app.workers.tasks._base import worker_session

__all__ = ["record_api_usage", "recompute_sales_ready", "write_audit"]


@app.task(name="app.workers.tasks.audit.write_audit", bind=True)
def write_audit(
    self,
    tenant_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_user_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> dict:
    with worker_session() as session:
        row = AuditLog(
            tenant_id=uuid.UUID(str(tenant_id)),
            actor_user_id=uuid.UUID(str(actor_user_id)) if actor_user_id else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before_json=before,
            after_json=after,
        )
        session.add(row)
        session.flush()
        return {"audit_id": str(row.id)}


@app.task(name="app.workers.tasks.audit.record_api_usage", bind=True)
def record_api_usage(
    self,
    tenant_id: str,
    provider: str,
    endpoint: str,
    unit_cost: float | None = None,
    request_count: int = 1,
) -> dict:
    with worker_session() as session:
        cost = None if unit_cost is None else Decimal(str(unit_cost))
        row = APIUsage(
            tenant_id=uuid.UUID(str(tenant_id)),
            provider=provider,
            endpoint=endpoint,
            request_count=request_count,
            unit_cost=cost,
            estimated_cost=(cost * request_count) if cost is not None else None,
        )
        session.add(row)
        session.flush()
        return {"api_usage_id": str(row.id)}


@app.task(name="app.workers.tasks.audit.recompute_sales_ready", bind=True)
def recompute_sales_ready(self, job_id: str) -> dict:
    jid = uuid.UUID(str(job_id))
    with worker_session() as session:
        job = session.get(MiningJob, jid)
        if job is None:
            return {"error": "job not found"}
        return stages.recompute_sales_ready_for_job(session, job)
