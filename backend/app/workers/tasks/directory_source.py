"""directory_source_jobs queue — gated public-directory discovery.

``run_directory_source(job_id, source_name)`` runs one gated directory source
(Yellow Pages / Clutch / Indeed) if the registry allows it; otherwise it logs a
skipped SourceRun and returns (the job continues). In the single-worker phase the
main discovery task already drains the directories source, so this task exists for
running an individual gated source on demand / re-runs.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.adapters.registry import get_registry
from app.constants import SourceName, SourceRunStatus
from app.models import DataSourceConfig, MiningJob
from app.pipeline import stages
from app.pipeline.runtime import build_job_spec, drain_async_iter
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import worker_session

__all__ = ["run_directory_source"]


@app.task(name="app.workers.tasks.directory_source.run_directory_source", bind=True)
def run_directory_source(self, job_id: str, source_name: str) -> dict:
    jid = uuid.UUID(str(job_id))
    with worker_session() as session:
        job = session.get(MiningJob, jid)
        if job is None:
            return {"error": "job not found"}
        name = SourceName(source_name)
        cfg = session.scalar(
            select(DataSourceConfig).where(
                DataSourceConfig.tenant_id == job.tenant_id,
                DataSourceConfig.source_name == name.value,
            )
        )
        registry = get_registry()
        resolved = registry.resolve_source(
            name,
            enabled=bool(cfg.enabled) if cfg else False,
            signed_off=bool(cfg and cfg.signoff_at is not None),
        )
        if not resolved.ok:
            session.add(
                stages._skipped_run(
                    job.id,
                    name.value,
                    resolved.unavailable.reason if resolved.unavailable else "unavailable",
                )
            )
            return {"skipped": name.value}

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
        index: dict = {}
        found = imported = 0
        for discovered in drain_async_iter(adapter.discover(build_job_spec(job), ctx)):
            found += 1
            _, created = stages._upsert_company(session, job, discovered, index)
            if created:
                imported += 1
        ctx.finalize(SourceRunStatus.COMPLETED, records_found=found, records_imported=imported)
        return {"source": name.value, "found": found, "imported": imported}
