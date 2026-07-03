"""Sales-ready lead projection — the clean output mirrored to Sales_Ready_Leads."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin
from app.models._shared import UUIDPk, uuid_fk

__all__ = ["SalesReadyLead"]


class SalesReadyLead(TimestampMixin, Base):
    __tablename__ = "sales_ready_leads"
    __table_args__ = (
        Index("ix_sales_ready_leads_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_sales_ready_leads_tenant_id_email", "tenant_id", "email"),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    job_id: Mapped[uuid.UUID | None] = uuid_fk("mining_jobs.id", ondelete="SET NULL", nullable=True)
    contact_id: Mapped[uuid.UUID | None] = uuid_fk(
        "contacts.id", ondelete="SET NULL", nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = uuid_fk(
        "companies.id", ondelete="SET NULL", nullable=True, index=False
    )
    company_name: Mapped[str] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(1000))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    designation: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    services: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_summary: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str | None] = mapped_column(String(30))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    last_verified_at: Mapped[datetime | None]
    campaign_status: Mapped[str | None] = mapped_column(String(50))
    # Sales-editable fields (round-tripped from the sheet; free text, not FKs).
    owner: Mapped[str | None] = mapped_column(String(255))
    next_action: Mapped[str | None] = mapped_column(String(255))
    sales_notes: Mapped[str | None] = mapped_column(Text)
    # Soft-delete: leads that later bounce/get suppressed are tombstoned, never reused.
    tombstoned: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int] = mapped_column(Integer, default=0)
