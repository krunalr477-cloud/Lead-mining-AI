"""export_jobs queue — produce CSV/XLSX/JSON exports of a tenant's sheet mirror.

``run_export(export_job_id)`` reads the Fake sheet mirror for the tenant and
writes the requested format to the exports dir, then marks the ExportJob done.
Works in demo mode against the FakeSheetsClient mirror.
"""

from __future__ import annotations

import csv
import json
import uuid

from app.config import REPO_ROOT
from app.constants import ExportFormat, JobStatus
from app.db import utcnow
from app.models import ExportJob
from app.sheetsync.client import FakeSheetsClient
from app.workers.celery_app import app
from app.workers.tasks._base import worker_session

__all__ = ["run_export"]

EXPORTS_DIR = REPO_ROOT / "exports"


@app.task(name="app.workers.tasks.export.run_export", bind=True)
def run_export(self, export_job_id: str) -> dict:
    eid = uuid.UUID(str(export_job_id))
    with worker_session() as session:
        export = session.get(ExportJob, eid)
        if export is None:
            return {"error": "export job not found"}
        try:
            client = FakeSheetsClient.load(export.tenant_id)
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            path = _write(client, export)
            export.file_path = str(path)
            export.status = JobStatus.COMPLETED
            export.completed_at = utcnow()
            return {"export_id": str(eid), "file": str(path), "format": export.format}
        except Exception as exc:  # record the failure on the row
            export.status = JobStatus.FAILED
            export.error = str(exc)[:1000]
            export.completed_at = utcnow()
            return {"export_id": str(eid), "error": str(exc)}


def _write(client: FakeSheetsClient, export: ExportJob):
    fmt = export.format
    if fmt == ExportFormat.XLSX:
        return client.dump_xlsx(EXPORTS_DIR / f"export_{export.id}.xlsx")
    if fmt == ExportFormat.JSON:
        path = EXPORTS_DIR / f"export_{export.id}.json"
        path.write_text(json.dumps(client.tabs, indent=2, default=str))
        return path
    # CSV: one file per tab is overkill; export the Sales_Ready_Leads tab (the
    # sales-facing clean output). Fall back to the first non-empty tab.
    path = EXPORTS_DIR / f"export_{export.id}.csv"
    empty_tab: dict = {"header": [], "rows": []}
    tab: dict = client.tabs.get("Sales_Ready_Leads") or next(
        (t for t in client.tabs.values() if t.get("rows")), empty_tab
    )
    header = tab["header"]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in tab["rows"]:
            writer.writerow({c: row.get(c, "") for c in header})
    return path
