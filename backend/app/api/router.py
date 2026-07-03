"""Aggregate /api/v1 router."""

from fastapi import APIRouter

from app.api import (
    audit,
    auth,
    bounces,
    campaigns,
    companies,
    contacts,
    dashboard,
    events,
    exports,
    health,
    integrations,
    jobs,
    settings,
    sheets,
    sources,
    suppressions,
    templates,
    users,
    validation,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(events.router)
router.include_router(jobs.router)
router.include_router(companies.router)
router.include_router(contacts.router)
router.include_router(validation.router)
router.include_router(sheets.router)
router.include_router(exports.router)
router.include_router(dashboard.router)
router.include_router(campaigns.router)
router.include_router(bounces.router)
router.include_router(templates.router)
router.include_router(suppressions.router)
router.include_router(settings.router)
router.include_router(sources.router)
router.include_router(integrations.router)
router.include_router(audit.router)
