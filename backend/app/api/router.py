"""Aggregate /api/v1 router."""

from fastapi import APIRouter

from app.api import (
    auth,
    companies,
    contacts,
    dashboard,
    events,
    health,
    jobs,
    sheets,
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
router.include_router(dashboard.router)
