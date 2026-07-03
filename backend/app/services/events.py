"""Job event stream: persist a JobEvent row, then fan out over Redis pub/sub.

Two entry points sharing one serializer:
- publish_event   (sync)  — Celery workers, scripts (sync Session)
- apublish_event  (async) — FastAPI request path (AsyncSession)

Each event is PUBLISHed as JSON to both ``job:{job_id}:events`` and
``tenant:{tenant_id}:events``; the SSE endpoints in app.api.events subscribe
to those channels. ``seq`` is a DB-generated monotonic cursor (BigInteger
Identity) used as the SSE event id for replay.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import redis
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import JobEvent

__all__ = [
    "apublish_event",
    "event_to_dict",
    "get_async_redis",
    "get_sync_redis",
    "job_channel",
    "publish_event",
    "serialize_event",
    "tenant_channel",
]


def job_channel(job_id: uuid.UUID | str) -> str:
    return f"job:{job_id}:events"


def tenant_channel(tenant_id: uuid.UUID | str) -> str:
    return f"tenant:{tenant_id}:events"


def event_to_dict(event: JobEvent) -> dict[str, Any]:
    """Wire format shared by pub/sub payloads, SSE frames, and the JSON fallback."""
    return {
        "seq": event.seq,
        "job_id": str(event.job_id),
        "stage": event.stage,
        "level": event.level,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def serialize_event(event: JobEvent) -> str:
    return json.dumps(event_to_dict(event), default=str)


_sync_redis: redis.Redis | None = None
_async_redis: aioredis.Redis | None = None


def get_sync_redis() -> redis.Redis:
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _sync_redis


def get_async_redis() -> aioredis.Redis:
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _async_redis


def _build_event(
    job_id: uuid.UUID,
    stage: str,
    level: str,
    message: str,
    payload: dict | None,
) -> JobEvent:
    return JobEvent(job_id=job_id, stage=stage, level=level, message=message, payload=payload)


def publish_event(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    stage: str,
    level: str = "info",
    message: str,
    payload: dict | None = None,
) -> JobEvent:
    """Insert a JobEvent (flushed, not committed — caller owns the transaction)
    and publish it to the job and tenant Redis channels. Sync path (workers)."""
    event = _build_event(job_id, stage, level, message, payload)
    session.add(event)
    session.flush()  # populates seq via INSERT .. RETURNING
    data = serialize_event(event)
    client = get_sync_redis()
    client.publish(job_channel(job_id), data)
    client.publish(tenant_channel(tenant_id), data)
    return event


async def apublish_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    stage: str,
    level: str = "info",
    message: str,
    payload: dict | None = None,
) -> JobEvent:
    """Async twin of publish_event for the FastAPI request path."""
    event = _build_event(job_id, stage, level, message, payload)
    session.add(event)
    await session.flush()  # populates seq via INSERT .. RETURNING
    data = serialize_event(event)
    client = get_async_redis()
    await client.publish(job_channel(job_id), data)
    await client.publish(tenant_channel(tenant_id), data)
    return event
