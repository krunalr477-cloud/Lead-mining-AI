"""Export jobs (CSV/XLSX/JSON downloads of mining results)."""

import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import ExportFormat, JobStatus
from app.db import Base, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

__all__ = ["ExportJob"]


class ExportJob(Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        Index("ix_export_jobs_tenant_id_created_at", "tenant_id", "created_at"),
        enum_check("format", ExportFormat),
        enum_check("status", JobStatus),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    job_id: Mapped[uuid.UUID | None] = uuid_fk("mining_jobs.id", ondelete="SET NULL", nullable=True)
    format: Mapped[str] = mapped_column(String(10), default=ExportFormat.CSV)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    # Local path or object-storage key, depending on the export driver.
    file_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None]
