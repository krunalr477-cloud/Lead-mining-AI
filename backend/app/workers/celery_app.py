"""Celery application for LeadMine AI.

Routing convention: every task module under ``app.workers.tasks`` is named
after its queue minus the ``_jobs`` suffix, so ``app.workers.tasks.<name>.*``
routes to ``<name>_jobs`` (the 12 queues in app.constants.QUEUES).

Error taxonomy:
- TransientError  -> auto-retried with exponential backoff + jitter
- PermanentError  -> fails immediately (bad input, 4xx, compliance block)
"""

import celery

from app.config import get_settings
from app.constants import QUEUES


class TransientError(Exception):
    """Retryable failure: rate limit, timeout, 429/5xx, flaky network."""


class PermanentError(Exception):
    """Non-retryable failure: bad input, 4xx, compliance block, invalid state."""


class LeadMineTask(celery.Task):
    """Base task: auto-retry on TransientError with exponential backoff."""

    autoretry_for = (TransientError,)
    retry_backoff = 2
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True


settings = get_settings()

app = celery.Celery("leadmine", broker=settings.redis_url, backend=settings.redis_url)
# All tasks (including @shared_task via this app) inherit retry semantics.
app.Task = LeadMineTask


def _task_routes() -> dict[str, dict[str, str]]:
    """`app.workers.tasks.<prefix>.*` -> `<prefix>_jobs` for the 12 queues."""
    return {
        f"app.workers.tasks.{queue.removesuffix('_jobs')}.*": {"queue": queue} for queue in QUEUES
    }


app.conf.update(
    task_routes=_task_routes(),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    # Task modules are imported via the tasks package as they land.
    imports=("app.workers.tasks",),
    # Beat schedule (spec §4/§13/§14).
    beat_schedule={
        "dispatch-due-campaign-messages": {
            "task": "app.workers.tasks.campaign.dispatch_due_messages",
            "schedule": 60,  # every 1 minute
        },
        "classify-deliveries": {
            "task": "app.workers.tasks.campaign.classify_deliveries",
            "schedule": 30 * 60,  # every 30 minutes
        },
        "poll-bounces": {
            "task": "app.workers.tasks.bounce.poll_bounces",
            "schedule": settings.bounce_poll_interval_minutes * 60,
        },
        "poll-replies": {
            "task": "app.workers.tasks.bounce.poll_replies",
            "schedule": settings.bounce_poll_interval_minutes * 60,
        },
        "retry-unknown-emails": {
            "task": "app.workers.tasks.validation.retry_unknown_batch",
            "schedule": 6 * 60 * 60,  # every 6 hours
        },
    },
)
