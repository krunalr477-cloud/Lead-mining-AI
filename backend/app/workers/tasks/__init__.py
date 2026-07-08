"""Celery task modules, one per queue.

Module names match the queue prefix so ``task_routes`` (app.workers.celery_app)
routes ``app.workers.tasks.<name>.*`` to ``<name>_jobs``::

    app.workers.tasks.google_maps       -> google_maps_jobs
    app.workers.tasks.website_scrape    -> website_scrape_jobs
    app.workers.tasks.directory_source  -> directory_source_jobs
    app.workers.tasks.facebook_signal   -> facebook_signal_jobs
    app.workers.tasks.job_signal        -> job_signal_jobs
    app.workers.tasks.enrichment        -> enrichment_jobs
    app.workers.tasks.validation        -> validation_jobs
    app.workers.tasks.spreadsheet_sync  -> spreadsheet_sync_jobs
    app.workers.tasks.export            -> export_jobs
    app.workers.tasks.audit             -> audit_jobs

campaign_jobs / bounce_check_jobs land in later phases.

Importing this package registers every task on the Celery app (celery_app's
``imports=("app.workers.tasks",)`` triggers this module).

WIRED vs. RESERVED (spec §P9): the mining pipeline currently runs *monolithically*
— ``jobs`` enqueues only ``google_maps.discover_places``, which drives every stage
in-process via ``orchestrator.advance`` (resumable + per-stage commit, so a
redelivery under ``acks_late`` resumes rather than re-spending). The per-unit
fan-out tasks (``website_scrape``, ``directory_source``, ``facebook_signal``,
``job_signal``, ``enrichment``, ``validation.validate_email``) and their queues are
RESERVED scaffolding for a future fan-out and are NOT enqueued today. Live tasks:
``google_maps.discover_places``, ``validation.retry_unknown_batch`` (beat),
``spreadsheet_sync``, ``export``, ``audit``, ``campaign.*``, ``bounce.*``. Do not
assume a queue is doing work just because it is routed here.
"""

from app.workers.tasks import (  # noqa: F401
    audit,
    bounce,
    campaign,
    directory_source,
    enrichment,
    export,
    facebook_signal,
    google_maps,
    job_signal,
    spreadsheet_sync,
    validation,
    website_scrape,
)
