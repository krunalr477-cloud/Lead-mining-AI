"""Integration: end-to-end export builds for every target (spec §12 / AC17).

Exercises :func:`app.services.exportsvc.build_export` against the live Postgres
schema for CSV / XLSX / JSON files AND the Google Sheets target — the latter
reuses the existing sheet-sync engine, driven in demo mode through the
FakeSheetsClient (no network). Each format lands a completed ExportJob with a
usable artifact; the sales_ready scope excludes non-verified leads.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.constants import (
    ExportFormat,
    ExportScope,
    ExportTarget,
    FinalEmailStatus,
    JobStatus,
)
from app.db import sync_session_factory
from app.models import ExportJob, SalesReadyLead, Tenant
from app.services import exportsvc
from app.sheetsync import client as sheets_client


@pytest.fixture
def session() -> Iterator[Session]:
    s = sync_session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def tenant(session: Session) -> Tenant:
    t = Tenant(name=f"export-flow-{uuid.uuid4().hex[:8]}")
    session.add(t)
    session.flush()
    return t


@pytest.fixture(autouse=True)
def _isolate_dirs(tmp_path, monkeypatch) -> None:
    # Keep both the export files and the FakeSheetsClient JSON mirror off the repo.
    monkeypatch.setattr(exportsvc, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(sheets_client, "EXPORTS_DIR", tmp_path / "mirror")


def _seed(session: Session, tenant: Tenant) -> None:
    session.add_all(
        [
            SalesReadyLead(
                tenant_id=tenant.id,
                company_name="Acme",
                email="ada@acme.example",
                validation_status=FinalEmailStatus.VERIFIED,
                rank=0,
            ),
            # Non-verified — must NOT reach any sales_ready export.
            SalesReadyLead(
                tenant_id=tenant.id,
                company_name="Beta",
                email="role@beta.example",
                validation_status=FinalEmailStatus.ROLE_BASED_REJECTED,
                rank=1,
            ),
        ]
    )
    session.flush()


@pytest.mark.parametrize("fmt", [ExportFormat.CSV, ExportFormat.XLSX, ExportFormat.JSON])
def test_file_export_completes_for_every_format(session: Session, tenant: Tenant, fmt: str) -> None:
    _seed(session, tenant)
    export = ExportJob(
        tenant_id=tenant.id,
        format=fmt,
        scope=ExportScope.SALES_READY,
        target=ExportTarget.FILE,
        status=JobStatus.QUEUED,
    )
    session.add(export)
    session.flush()

    result = exportsvc.build_export(session, export.id)

    assert result["status"] == JobStatus.COMPLETED
    assert result["rows"] == 1  # only the verified lead
    path = Path(export.file_path)
    assert path.exists() and path.stat().st_size > 0


def test_google_sheets_target_reuses_sync_engine(session: Session, tenant: Tenant) -> None:
    _seed(session, tenant)
    export = ExportJob(
        tenant_id=tenant.id,
        format=ExportFormat.CSV,  # ignored for the sheets target
        scope=ExportScope.SALES_READY,
        target=ExportTarget.GOOGLE_SHEETS,
        status=JobStatus.QUEUED,
    )
    session.add(export)
    session.flush()

    result = exportsvc.build_export(session, export.id)

    assert result["status"] == JobStatus.COMPLETED
    assert result["target"] == ExportTarget.GOOGLE_SHEETS
    # run_sync stamped the tenant's spreadsheet id and recorded it as file_path.
    assert export.file_path == f"fake-sheet-{tenant.id}"
    assert result["spreadsheet_id"] == export.file_path
    # The engine flushed every DB-backed tab (README skipped) and appended the
    # single verified sales-ready lead.
    assert result["tabs"] >= 1
    assert result["appended"] >= 1

    tenant_refetched = session.get(Tenant, tenant.id)
    assert tenant_refetched.google_spreadsheet_id == f"fake-sheet-{tenant.id}"

    # The mirror written by the FakeSheetsClient carries only the verified lead.
    mirror = Path(sheets_client.EXPORTS_DIR) / f"sheets_mirror_{tenant.id}.json"
    data = json.loads(mirror.read_text())
    emails = {r["email"] for r in data["tabs"]["Sales_Ready_Leads"]["rows"]}
    assert emails == {"ada@acme.example"}
