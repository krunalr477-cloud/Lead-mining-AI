"""Liveness and readiness probes."""

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import async_session_factory

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict[str, object]:
    """Ready only when both Postgres and Redis answer."""
    checks: dict[str, str] = {}

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"

    client = aioredis.from_url(get_settings().redis_url)
    try:
        await client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"
    finally:
        await client.aclose()

    if any(value != "ok" for value in checks.values()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unavailable", "checks": checks},
        )
    return {"status": "ok", "checks": checks}


@router.get("/workers/health")
async def workers_health() -> dict[str, object]:
    """Report whether any Celery worker is alive (spec §O1).

    Queued jobs silently stall when no worker is running (a common footgun when
    the worker was a session-bound process). This broadcasts a short-timeout ping
    so the UI can show a "workers up?" indicator instead of leaving jobs stuck at
    ``queued`` with no explanation. ``up=false`` is a normal answer (not a 5xx) so
    the frontend can render it without treating it as an error."""

    def _ping() -> list[str]:
        try:
            from app.workers.celery_app import app as celery_app

            replies = celery_app.control.ping(timeout=1.0) or []
            return [name for reply in replies for name in reply]
        except Exception:
            return []

    workers = await run_in_threadpool(_ping)
    return {"status": "ok" if workers else "down", "up": bool(workers), "workers": workers}
