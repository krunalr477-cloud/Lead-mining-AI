"""SSE endpoints for live job / tenant event streams (with JSON polling fallback).

- GET /jobs/{job_id}/events  — replay JobEvent rows after Last-Event-ID (or
  ?after_seq=N), then live-stream from the ``job:{id}:events`` Redis channel.
  Event id = seq, so EventSource reconnects resume exactly where they left off.
  Accept: application/json (or ?format=json) returns a plain JSON list instead.
- GET /events                — tenant-wide live stream (no replay).

Heartbeats are SSE comments every 15s (sse-starlette's built-in ping).
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.db import async_session_factory
from app.deps import CurrentUser, TenantId
from app.models import JobEvent, MiningJob
from app.services.events import (
    event_to_dict,
    get_async_redis,
    job_channel,
    serialize_event,
    tenant_channel,
)

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15
# Subscription poll timeout; heartbeats are handled by EventSourceResponse(ping=...).
_PUBSUB_POLL_SECONDS = 5.0


async def _ensure_job_visible(job_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        found = await session.scalar(
            select(MiningJob.id).where(MiningJob.id == job_id, MiningJob.tenant_id == tenant_id)
        )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


async def _replay_rows(job_id: uuid.UUID, after_seq: int) -> list[JobEvent]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq > after_seq)
            .order_by(JobEvent.seq)
        )
        return list(rows)


def _resolve_cursor(request: Request, after_seq: int | None) -> int:
    """?after_seq= wins; otherwise the Last-Event-ID reconnect header; else 0."""
    if after_seq is not None:
        return after_seq
    raw = request.headers.get("last-event-id", "")
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _wants_json(request: Request, format_param: str | None) -> bool:
    if format_param == "json":
        return True
    if format_param == "sse":
        return False
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/event-stream" not in accept


async def _job_stream(
    request: Request, job_id: uuid.UUID, after_seq: int
) -> AsyncIterator[dict[str, str]]:
    client = get_async_redis()
    pubsub = client.pubsub()
    # Subscribe BEFORE replaying so no event falls in the replay/live gap;
    # duplicates in the overlap are dropped by the seq cursor below.
    await pubsub.subscribe(job_channel(job_id))
    try:
        last_seq = after_seq
        for row in await _replay_rows(job_id, after_seq):
            last_seq = row.seq
            yield {"id": str(row.seq), "data": serialize_event(row)}
        while not await request.is_disconnected():
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_PUBSUB_POLL_SECONDS
            )
            if message is None:
                continue
            try:
                seq = int(json.loads(message["data"]).get("seq") or 0)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if seq <= last_seq:
                continue
            last_seq = seq
            yield {"id": str(seq), "data": message["data"]}
    finally:
        await pubsub.unsubscribe(job_channel(job_id))
        await pubsub.aclose()


async def _tenant_stream(request: Request, tenant_id: uuid.UUID) -> AsyncIterator[dict[str, str]]:
    client = get_async_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(tenant_channel(tenant_id))
    try:
        while not await request.is_disconnected():
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_PUBSUB_POLL_SECONDS
            )
            if message is None:
                continue
            try:
                seq = json.loads(message["data"]).get("seq")
            except (ValueError, json.JSONDecodeError):
                seq = None
            frame = {"data": message["data"]}
            if seq is not None:
                frame["id"] = str(seq)
            yield frame
    finally:
        await pubsub.unsubscribe(tenant_channel(tenant_id))
        await pubsub.aclose()


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: uuid.UUID,
    request: Request,
    _user: CurrentUser,
    tenant_id: TenantId,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    format: Annotated[str | None, Query(pattern="^(json|sse)$")] = None,
):
    """Replay-then-live SSE stream of a job's events (JSON list for pollers)."""
    await _ensure_job_visible(job_id, tenant_id)
    cursor = _resolve_cursor(request, after_seq)
    if _wants_json(request, format):
        return [event_to_dict(row) for row in await _replay_rows(job_id, cursor)]
    return EventSourceResponse(_job_stream(request, job_id, cursor), ping=HEARTBEAT_SECONDS)


@router.get("/events")
async def tenant_events(
    request: Request,
    _user: CurrentUser,
    tenant_id: TenantId,
):
    """Tenant-wide live SSE stream (no replay; heartbeat comments keep it open)."""
    return EventSourceResponse(_tenant_stream(request, tenant_id), ping=HEARTBEAT_SECONDS)
