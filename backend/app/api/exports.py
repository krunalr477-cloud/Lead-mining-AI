"""Export endpoints (spec §12 output / §19 /exports / AC17).

POST /exports        create an ExportJob (format, scope, target, job_id) + enqueue
GET  /exports/{id}   status + a download path/URL when completed
GET  /exports        list a tenant's export jobs (most recent first)

Exports cover CSV, XLSX, JSON, and Google Sheets. ``scope=sales_ready`` yields
the clean verified output; ``scope=raw`` yields the full mined dataset.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.constants import ExportFormat, ExportScope, ExportTarget, JobStatus
from app.deps import SessionDep, TenantId, require
from app.models import ExportJob, MiningJob, Tenant

router = APIRouter(prefix="/exports", tags=["exports"])

ReadActor = Annotated[Tenant, Depends(require("exports:read"))]
CreateActor = Annotated[Tenant, Depends(require("exports:create"))]


class ExportCreate(BaseModel):
    format: ExportFormat = ExportFormat.CSV
    scope: ExportScope = ExportScope.SALES_READY
    target: ExportTarget = ExportTarget.FILE
    job_id: uuid.UUID | None = Field(
        default=None, description="Scope the export to one mining job (optional)."
    )


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    job_id: uuid.UUID | None
    format: str
    scope: str
    target: str
    status: str
    file_path: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


def _download_url(export: ExportJob) -> str | None:
    """A client-facing pointer to the finished artifact, or None if not ready."""
    if export.status != JobStatus.COMPLETED or not export.file_path:
        return None
    if export.target == ExportTarget.GOOGLE_SHEETS:
        return f"https://docs.google.com/spreadsheets/d/{export.file_path}"
    return f"/api/v1/exports/{export.id}/download"


@router.post("", response_model=ExportOut, status_code=status.HTTP_201_CREATED)
async def create_export(
    body: ExportCreate,
    _actor: CreateActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> ExportJob:
    if body.job_id is not None:
        job = await session.get(MiningJob, body.job_id)
        if job is None or job.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    export = ExportJob(
        tenant_id=tenant_id,
        job_id=body.job_id,
        format=body.format.value,
        scope=body.scope.value,
        target=body.target.value,
        status=JobStatus.QUEUED,
    )
    session.add(export)
    await session.commit()
    await session.refresh(export)

    # Enqueue the build on the export_jobs queue.
    from app.workers.tasks.export import build_export

    build_export.delay(str(export.id))
    return export


@router.get("", response_model=list[ExportOut])
async def list_exports(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    job_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExportJob]:
    from sqlalchemy import select

    stmt = select(ExportJob).where(ExportJob.tenant_id == tenant_id)
    if job_id is not None:
        stmt = stmt.where(ExportJob.job_id == job_id)
    stmt = stmt.order_by(ExportJob.created_at.desc()).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


@router.get("/{export_id}")
async def get_export(
    export_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> dict:
    export = await session.get(ExportJob, export_id)
    if export is None or export.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    return {
        **ExportOut.model_validate(export).model_dump(mode="json"),
        "download_url": _download_url(export),
    }


_MEDIA_TYPES = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.JSON: "application/json",
}


@router.get("/{export_id}/download")
async def download_export(
    export_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> FileResponse:
    from pathlib import Path

    export = await session.get(ExportJob, export_id)
    if export is None or export.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    if export.target == ExportTarget.GOOGLE_SHEETS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Google Sheets exports have no file"
        )
    if export.status != JobStatus.COMPLETED or not export.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Export is {export.status}"
        )
    path = Path(export.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export file missing")
    media_type = _MEDIA_TYPES.get(ExportFormat(export.format), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)
