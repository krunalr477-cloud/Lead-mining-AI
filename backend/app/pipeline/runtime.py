"""Shared runtime helpers for the worker pipeline (sync side).

Small, dependency-light utilities used by the orchestrator and every task module:
- ``drain_async_iter`` / ``run_async`` — drive the async adapter API from a sync
  Celery worker.
- Redis fan-out counters — ``job:{id}:stage:{name}:pending`` gates a stage's
  transition until every unit task has decremented it (the task hitting 0 advances
  the job). Rebuildable from the DB, so a restart is safe.
- Cancel/pause flags — ``job:{id}:cancelled`` (Redis) + the MiningJob.status
  boundary check.
- ``build_job_spec`` / ``load_rules`` — turn a MiningJob row into the dataclasses
  the adapters/validation expect.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.adapters.base import JobSpec
from app.models import MiningJob, ValidationRuleSet
from app.pipeline.validation import RuleSet

if TYPE_CHECKING:
    import redis
    from sqlalchemy.orm import Session

__all__ = [
    "RESTARTABLE_COUNTER_TTL",
    "build_job_spec",
    "cancel_key",
    "clear_stage_counter",
    "decr_stage_counter",
    "drain_async_iter",
    "is_cancelled",
    "load_rules",
    "mark_cancelled",
    "run_async",
    "set_stage_counter",
    "stage_counter_key",
]

# Counters expire after a day of inactivity — a stalled job cleans itself up.
RESTARTABLE_COUNTER_TTL = 86_400


# --------------------------------------------------------------------------- #
# Async <-> sync bridge
# --------------------------------------------------------------------------- #


def run_async(coro):
    """Run an async coroutine to completion from sync worker code."""
    return asyncio.run(coro)


def drain_async_iter[T](agen: AsyncIterator[T]) -> list[T]:
    """Fully drain an async iterator into a list (sync worker helper)."""

    async def _collect() -> list[T]:
        return [item async for item in agen]

    return asyncio.run(_collect())


# --------------------------------------------------------------------------- #
# Redis fan-out counters + cancel flags
# --------------------------------------------------------------------------- #


def stage_counter_key(job_id: uuid.UUID | str, stage: str) -> str:
    return f"job:{job_id}:stage:{stage}:pending"


def cancel_key(job_id: uuid.UUID | str) -> str:
    return f"job:{job_id}:cancelled"


def set_stage_counter(redis_client: redis.Redis, job_id, stage: str, count: int) -> None:
    key = stage_counter_key(job_id, stage)
    pipe = redis_client.pipeline()
    pipe.set(key, count)
    pipe.expire(key, RESTARTABLE_COUNTER_TTL)
    pipe.execute()


def decr_stage_counter(redis_client: redis.Redis, job_id, stage: str) -> int:
    """Decrement the fan-out counter; returns the remaining count (>=0)."""
    remaining = redis_client.decr(stage_counter_key(job_id, stage))
    return max(0, int(remaining))  # type: ignore[arg-type]


def clear_stage_counter(redis_client: redis.Redis, job_id, stage: str) -> None:
    redis_client.delete(stage_counter_key(job_id, stage))


def mark_cancelled(redis_client: redis.Redis, job_id) -> None:
    key = cancel_key(job_id)
    redis_client.set(key, "1")
    redis_client.expire(key, RESTARTABLE_COUNTER_TTL)


def is_cancelled(redis_client: redis.Redis, job_id) -> bool:
    return bool(redis_client.exists(cancel_key(job_id)))


# --------------------------------------------------------------------------- #
# Row -> dataclass adapters
# --------------------------------------------------------------------------- #


def build_job_spec(job: MiningJob) -> JobSpec:
    """Normalize a MiningJob row into the JobSpec adapters consume."""
    return JobSpec(
        job_id=job.id,
        tenant_id=job.tenant_id,
        company_type=job.company_type,
        services=list(job.services or []),
        country=job.country,
        state=job.state,
        city=job.city,
        zipcode=job.zipcode,
        latitude=float(job.latitude) if job.latitude is not None else None,
        longitude=float(job.longitude) if job.longitude is not None else None,
        radius_km=float(job.radius_km) if job.radius_km is not None else None,
        company_size_min=job.company_size_min,
        company_size_max=job.company_size_max,
        contact_roles=list(job.contact_roles or []),
        exclude_keywords=list(job.exclude_keywords or []),
        deep_discovery=bool(
            ((job.totals_json or {}).get("job_options") or {}).get("deep_discovery", False)
        ),
    )


def load_rules(session: Session, tenant_id: uuid.UUID) -> RuleSet:
    """Load the tenant validation RuleSet (defaults when no row exists)."""
    from sqlalchemy import select

    row = session.scalar(select(ValidationRuleSet).where(ValidationRuleSet.tenant_id == tenant_id))
    return RuleSet.from_dict(row.rules if row is not None else None)
