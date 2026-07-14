"""FastAPI application factory."""

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import compat_router as compat_auth_router
from app.api.router import router as api_router
from app.config import get_settings


def configure_logging(environment: str) -> None:
    renderer = (
        structlog.dev.ConsoleRenderer()
        if environment == "development"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        cache_logger_on_first_use=True,
    )


async def _seed_demo_data():
    """Auto-seed demo data on first startup if the demo tenant doesn't exist yet."""
    try:
        from app.db import sync_session_factory
        from app.models import Tenant
        from app.constants import DEMO_TENANT_ID

        session = sync_session_factory()
        try:
            tenant = session.get(Tenant, DEMO_TENANT_ID)
            if tenant is None:
                import structlog as _sl
                log = _sl.get_logger(__name__)
                log.info("demo_tenant_missing, seeding demo data now")
                from app.seeds.demo import seed_demo
                result = seed_demo(session=session)
                session.commit()
                log.info("demo_seed_complete", result=result)
            else:
                log = structlog.get_logger(__name__)
                log.info("demo_tenant_exists, skipping seed")
        finally:
            session.close()
    except Exception as e:
        import structlog as _sl
        log = _sl.get_logger(__name__)
        log.error("demo_seed_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-seed demo data on startup
    await _seed_demo_data()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.environment)

    # In production/deployed mode, allow all origins so the frontend can
    # connect from any domain. In development, restrict to frontend_url.
    is_dev = settings.environment == "development"
    cors_origins = (
        [settings.frontend_url]
        if is_dev and settings.frontend_url
        else ["*"]
    )

    app = FastAPI(
        title="LeadMine AI",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    # Root-level OAuth callback aliases (e.g. /auth/callback) for OAuth clients
    # registered with a short redirect URI. No /api/v1 prefix.
    app.include_router(compat_auth_router)
    return app


app = create_app()
