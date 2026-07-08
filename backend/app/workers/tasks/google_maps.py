"""google_maps_jobs queue — company discovery from Google Maps + directories.

``discover_places(job_id)`` runs the discovery + dedupe stage (all selected
discovery sources), then transitions the job to extraction via the orchestrator.
Named for the queue (``app.workers.tasks.google_maps`` -> ``google_maps_jobs``).
"""

from __future__ import annotations

import uuid

from app.pipeline.orchestrator import advance
from app.workers.celery_app import app

__all__ = ["discover_places"]


@app.task(name="app.workers.tasks.google_maps.discover_places", bind=True)
def discover_places(self, job_id: str) -> dict:
    """Drive the whole mining pipeline for a job.

    ``advance`` owns discovery→extraction→enrichment→validation→sales-ready→sync,
    committing per stage and marking the job FAILED on error. Running discovery
    here separately (as before) caused it to run twice — ``advance`` re-entered
    the DISCOVERING stage because progress was still 0 — so discovery now lives
    entirely inside ``advance``.
    """
    jid = uuid.UUID(str(job_id))
    advance(jid)
    return {"job_id": str(jid)}
