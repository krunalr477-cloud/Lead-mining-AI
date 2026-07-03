"""job_signal_jobs queue — Google/SERP jobs hiring-signal extraction.

``run_job_signals(job_id, company_id)`` attaches public job-posting signals to a
company IF the SERP jobs source is enabled + signed off + the gated-sources flag
is on; otherwise it logs a skipped SourceRun and returns (the job continues).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.adapters.base import CompanyRef
from app.adapters.registry import get_registry
from app.constants import SourceName, SourceRunStatus
from app.models import Company, DataSourceConfig, MiningJob
from app.pipeline import stages
from app.pipeline.runtime import run_async
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import worker_session

__all__ = ["run_job_signals"]


@app.task(name="app.workers.tasks.job_signal.run_job_signals", bind=True)
def run_job_signals(self, job_id: str, company_id: str) -> dict:
    jid = uuid.UUID(str(job_id))
    cid = uuid.UUID(str(company_id))
    with worker_session() as session:
        job = session.get(MiningJob, jid)
        company = session.get(Company, cid)
        if job is None or company is None:
            return {"error": "job or company not found"}
        cfg = session.scalar(
            select(DataSourceConfig).where(
                DataSourceConfig.tenant_id == job.tenant_id,
                DataSourceConfig.source_name == SourceName.SERP_JOBS.value,
            )
        )
        registry = get_registry()
        resolved = registry.resolve_source(
            SourceName.SERP_JOBS,
            enabled=bool(cfg.enabled) if cfg else False,
            signed_off=bool(cfg and cfg.signoff_at is not None),
        )
        if not resolved.ok:
            session.add(
                stages._skipped_run(
                    job.id,
                    SourceName.SERP_JOBS.value,
                    resolved.unavailable.reason if resolved.unavailable else "gated",
                )
            )
            return {"skipped": SourceName.SERP_JOBS.value}
        adapter = resolved.adapter
        assert adapter is not None
        ctx = registry.build_context(
            session=session,
            redis_client=get_redis(),
            tenant_id=job.tenant_id,
            job_id=job.id,
            adapter=adapter,
        )
        ctx.open()
        ref = CompanyRef(
            company_id=company.id,
            name=company.canonical_name,
            website=company.website,
            domain=company.domain,
            city=company.city,
            country=company.country,
        )
        result = run_async(adapter.extract(ref, ctx))
        added = stages._apply_signals(session, company, result)
        ctx.finalize(SourceRunStatus.COMPLETED, records_found=added, records_imported=added)
        if added:
            company.hiring_signal_status = "signals_found"
        return {"signals": added}
