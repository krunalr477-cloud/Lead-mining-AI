"""spreadsheet_sync_jobs queue — flush the DB→Sheets mirror.

``flush_sheet_tab(tenant_id, tab)`` flushes one tab; ``flush_all_tabs`` flushes
every DB-backed tab; ``setup_spreadsheet`` ensures the spreadsheet + 12 tabs +
headers exist.
"""

from __future__ import annotations

import uuid

from app.pipeline import stages
from app.sheetsync.client import FakeSheetsClient
from app.sheetsync.engine import SheetSyncEngine
from app.workers.celery_app import app
from app.workers.tasks._base import worker_session

__all__ = ["flush_all_tabs", "flush_sheet_tab", "setup_spreadsheet"]


@app.task(name="app.workers.tasks.spreadsheet_sync.setup_spreadsheet", bind=True)
def setup_spreadsheet(self, tenant_id: str) -> dict:
    tid = uuid.UUID(str(tenant_id))
    with worker_session() as session:
        engine = SheetSyncEngine(session, FakeSheetsClient.load(tid))
        spreadsheet_id = engine.setup_spreadsheet(tid)
    return {"spreadsheet_id": spreadsheet_id}


@app.task(name="app.workers.tasks.spreadsheet_sync.flush_sheet_tab", bind=True)
def flush_sheet_tab(self, tenant_id: str, tab: str) -> dict:
    tid = uuid.UUID(str(tenant_id))
    with worker_session() as session:
        engine = SheetSyncEngine(session, FakeSheetsClient.load(tid))
        engine.setup_spreadsheet(tid)
        result = engine.flush_tab(tid, tab)
    return {"tab": result.tab, "appended": result.appended, "updated": result.updated}


@app.task(name="app.workers.tasks.spreadsheet_sync.flush_all_tabs", bind=True)
def flush_all_tabs(self, tenant_id: str) -> dict:
    tid = uuid.UUID(str(tenant_id))
    with worker_session() as session:
        return stages.run_sync(session, tid)
