"""google_maps_jobs queue — company discovery from Google Maps + directories.

``discover_places(job_id)`` runs the discovery + dedupe stage (all selected
discovery sources), then transitions the job to extraction via the orchestrator.
Named for the queue (``app.workers.tasks.google_maps`` -> ``google_maps_jobs``).
"""

from __future__ import annotations

import uuid

from app.models import MiningJob
from app.pipeline import stages
from app.pipeline.orchestrator import advance
from app.workers.celery_app import app
from app.workers.rate_limit import get_redis
from app.workers.tasks._base import worker_session

__all__ = ["discover_places"]


@app.task(name="app.workers.tasks.google_maps.discover_places", bind=True)
def discover_places(self, job_id: str) -> dict:
    jid = uuid.UUID(str(job_id))
    with worker_session() as session:
        job = session.get(MiningJob, jid)
        if job is None:
            return {"error": "job not found"}
        result = stages.run_discovery(session, get_redis(), job)
    # Transition to the next stage (extraction fan-out) after discovery commits.
    advance(jid)
    return result
