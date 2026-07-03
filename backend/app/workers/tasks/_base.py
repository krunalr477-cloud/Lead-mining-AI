"""Shared task helpers: session + redis handles, fan-out counter decrement.

Every task uses ``sync_session_factory`` (workers are sync), the shared Redis
client, and — for fan-out stages — ``finish_unit`` in a ``finally`` so the
counter is always decremented even on failure; the task that drops it to zero
calls ``orchestrator.advance`` to transition the job.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.db import sync_session_factory
from app.pipeline.runtime import decr_stage_counter
from app.workers.rate_limit import get_redis

__all__ = ["finish_unit", "worker_session"]


@contextmanager
def worker_session() -> Iterator[Session]:
    session = sync_session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def finish_unit(job_id: uuid.UUID, stage: str) -> None:
    """Decrement the stage fan-out counter; advance the job when it hits zero."""
    redis_client = get_redis()
    remaining = decr_stage_counter(redis_client, job_id, stage)
    if remaining <= 0:
        # Import here to avoid a circular import at module load.
        from app.pipeline.orchestrator import advance

        advance(job_id)
