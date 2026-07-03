"""Liveness and readiness probes."""

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

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
