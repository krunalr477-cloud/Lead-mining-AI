"""website_scrape_jobs queue — per-company crawl + contact/signal extraction.

``crawl_company_site(job_id, company_id, stage)`` deep-dives one company. When run
in a fan-out (``stage`` supplied) it decrements the extraction counter in a
``finally`` so the last company advances the job.
"""

from __future__ import annotations

import uuid

from app.models import Company, MiningJob
from app.pipeline import stages
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import finish_unit, worker_session

__all__ = ["crawl_company_site"]


@app.task(name="app.workers.tasks.website_scrape.crawl_company_site", bind=True)
def crawl_company_site(self, job_id: str, company_id: str, stage: str | None = None) -> dict:
    jid = uuid.UUID(str(job_id))
    cid = uuid.UUID(str(company_id))
    result: dict = {"company_id": str(cid)}
    try:
        with worker_session() as session:
            job = session.get(MiningJob, jid)
            company = session.get(Company, cid)
            if job is None or company is None:
                return {"error": "job or company not found"}
            result.update(stages.run_extraction(session, get_redis(), job, company))
        return result
    finally:
        if stage:
            finish_unit(jid, stage)
