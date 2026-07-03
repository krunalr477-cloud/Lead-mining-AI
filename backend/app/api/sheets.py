"""Google Sheets sync endpoints (spec §19). Demo mode = FakeSheetsClient mirror.

POST /sheets/connect   initialize the (fake) spreadsheet mirror + 12 tabs
GET  /sheets/status    connected spreadsheet, tabs, last sync, failed rows
POST /sheets/sync      flush all DB-backed tabs
GET  /sheets/events    recent SpreadsheetSyncEvent rows
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.constants import SyncStatus
from app.deps import SessionDep, TenantId, require
from app.models import SheetRowMap, SpreadsheetSyncEvent, Tenant

router = APIRouter(prefix="/sheets", tags=["sheets"])

ReadActor = Annotated[Tenant, Depends(require("sheets:read"))]
SyncActor = Annotated[Tenant, Depends(require("sheets:sync"))]


@router.post("/connect")
async def connect_sheets(_actor: SyncActor, tenant_id: TenantId, session: SessionDep) -> dict:
    spreadsheet_id = await run_in_threadpool(_setup, tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is not None:
        tenant.google_spreadsheet_id = spreadsheet_id
        await session.commit()
    return {"spreadsheet_id": spreadsheet_id, "connected": True}


@router.get("/status")
async def sheets_status(_actor: ReadActor, tenant_id: TenantId, session: SessionDep) -> dict:
    tenant = await session.get(Tenant, tenant_id)
    tab_counts: dict[str, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(SheetRowMap.tab, func.count())
                .where(SheetRowMap.tenant_id == tenant_id)
                .group_by(SheetRowMap.tab)
            )
        ).all()
    }
    last_synced = await session.scalar(
        select(func.max(SpreadsheetSyncEvent.synced_at)).where(
            SpreadsheetSyncEvent.tenant_id == tenant_id
        )
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(SpreadsheetSyncEvent)
        .where(
            SpreadsheetSyncEvent.tenant_id == tenant_id,
            SpreadsheetSyncEvent.status == SyncStatus.PENDING,
        )
    )
    failed = await session.scalar(
        select(func.count())
        .select_from(SpreadsheetSyncEvent)
        .where(
            SpreadsheetSyncEvent.tenant_id == tenant_id,
            SpreadsheetSyncEvent.status == SyncStatus.FAILED,
        )
    )
    return {
        "connected": bool(tenant and tenant.google_spreadsheet_id),
        "spreadsheet_id": tenant.google_spreadsheet_id if tenant else None,
        "tabs": tab_counts,
        "row_count": sum(tab_counts.values()),
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        "pending_rows": int(pending or 0),
        "failed_rows": int(failed or 0),
    }


@router.post("/sync")
async def sync_sheets(_actor: SyncActor, tenant_id: TenantId) -> dict:
    return await run_in_threadpool(_flush_all, tenant_id)


@router.get("/events")
async def sheet_events(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict]:
    events = list(
        await session.scalars(
            select(SpreadsheetSyncEvent)
            .where(SpreadsheetSyncEvent.tenant_id == tenant_id)
            .order_by(SpreadsheetSyncEvent.created_at.desc())
            .limit(limit)
        )
    )
    return [
        {
            "id": str(e.id),
            "sheet_tab": e.sheet_tab,
            "row_key": e.row_key,
            "operation": e.operation,
            "status": e.status,
            "error_message": e.error_message,
            "synced_at": e.synced_at.isoformat() if e.synced_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


# --------------------------------------------------------------------------- #
# Sync helpers (threadpool — sync Session)
# --------------------------------------------------------------------------- #


def _setup(tenant_id: uuid.UUID) -> str:
    from app.db import sync_session_factory
    from app.sheetsync.engine import SheetSyncEngine
    from app.sheetsync.factory import get_sheets_client

    with sync_session_factory() as session:
        engine = SheetSyncEngine(session, get_sheets_client(tenant_id, session))
        spreadsheet_id = engine.setup_spreadsheet(tenant_id)
        session.commit()
    return spreadsheet_id


def _flush_all(tenant_id: uuid.UUID) -> dict:
    from app.db import sync_session_factory
    from app.pipeline.stages import run_sync

    with sync_session_factory() as session:
        result = run_sync(session, tenant_id)
        session.commit()
    return result
