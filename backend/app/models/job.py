"""Mining job aggregate: jobs, per-source runs, event stream, compliance audit."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Identity, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import AccessMethod, JobStage, JobStatus, Posture, SourceRunStatus
from app.db import Base, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

__all__ = ["DataSourceAuditEvent", "JobEvent", "MiningJob", "SourceRun"]


class MiningJob(Base):
    __tablename__ = "mining_jobs"
    __table_args__ = (
        Index("ix_mining_jobs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_mining_jobs_tenant_id_status", "tenant_id", "status"),
        enum_check("status", JobStatus),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    created_by: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL", nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    company_type: Mapped[str | None] = mapped_column(String(255))
    services: Mapped[list[str]] = mapped_column(JSONB, default=list)
    country: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    zipcode: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    radius_km: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    company_size_min: Mapped[int | None] = mapped_column(Integer)
    company_size_max: Mapped[int | None] = mapped_column(Integer)
    contact_roles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    exclude_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    selected_sources: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.DRAFT)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    totals_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]

    source_runs: Mapped[list["SourceRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="JobEvent.seq",
    )


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = (
        enum_check("status", SourceRunStatus),
        enum_check("access_method", AccessMethod),
        enum_check("compliance_posture", Posture),
    )

    id: Mapped[UUIDPk]
    job_id: Mapped[uuid.UUID] = uuid_fk("mining_jobs.id", ondelete="CASCADE")
    source_name: Mapped[str] = mapped_column(String(50))
    access_method: Mapped[str] = mapped_column(String(30))
    compliance_posture: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default=SourceRunStatus.PENDING)
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_imported: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]

    job: Mapped[MiningJob] = relationship(back_populates="source_runs")


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        Index("ix_job_events_job_id_seq", "job_id", "seq"),
        enum_check("stage", JobStage),
    )

    id: Mapped[UUIDPk]
    job_id: Mapped[uuid.UUID] = uuid_fk("mining_jobs.id", ondelete="CASCADE", index=False)
    # Monotonic per-table sequence: cheap cursor for SSE replay ("events after seq N").
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    stage: Mapped[str | None] = mapped_column(String(30))
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    job: Mapped[MiningJob] = relationship(back_populates="events")


class DataSourceAuditEvent(Base):
    __tablename__ = "data_source_audit_events"
    __table_args__ = (
        Index("ix_data_source_audit_events_tenant_id_created_at", "tenant_id", "created_at"),
        enum_check("access_method", AccessMethod),
        enum_check("compliance_posture", Posture),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    job_id: Mapped[uuid.UUID | None] = uuid_fk("mining_jobs.id", ondelete="SET NULL", nullable=True)
    source_run_id: Mapped[uuid.UUID | None] = uuid_fk(
        "source_runs.id", ondelete="SET NULL", nullable=True, index=False
    )
    source_name: Mapped[str] = mapped_column(String(50))
    source_type: Mapped[str | None] = mapped_column(String(50))
    access_method: Mapped[str] = mapped_column(String(30))
    compliance_posture: Mapped[str] = mapped_column(String(10))
    url_or_endpoint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50))
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
