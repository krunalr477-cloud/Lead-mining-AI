"""export_jobs queue — produce CSV/XLSX/JSON (or Google Sheets) exports.

``build_export(export_job_id)`` materializes an :class:`ExportJob` through
:func:`app.services.exportsvc.build_export`: it reads the tenant's DB-backed rows
via the sheet TabSpecs (so the sales-ready filter and scalarization match the
spreadsheet), writes the requested format under ``exports/``, and marks the row
done. The ``google_sheets`` target reuses the sheet-sync engine.

``run_export`` is kept as a backward-compatible alias of ``build_export``.
"""

from __future__ import annotations

import uuid

from app.services.exportsvc import build_export as _build_export
from app.workers.celery_app import app
from app.workers.tasks._base import worker_session

__all__ = ["build_export", "run_export"]


@app.task(name="app.workers.tasks.export.build_export", bind=True)
def build_export(self, export_job_id: str) -> dict:
    eid = uuid.UUID(str(export_job_id))
    with worker_session() as session:
        return _build_export(session, eid)


# Backward-compatible name for earlier callers/tests.
run_export = build_export
