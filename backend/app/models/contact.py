"""Contact aggregate: contacts, discovered email candidates, validation checks."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import (
    EnrichmentStatus,
    FinalEmailStatus,
    MillionVerifierStatus,
    StageStatus,
)
from app.db import Base, TimestampMixin, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

if TYPE_CHECKING:
    from app.models.company import Company

__all__ = ["Contact", "EmailCandidate", "ValidationCheck"]


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_contacts_tenant_id_email", "tenant_id", "email"),
        enum_check("enrichment_status", EnrichmentStatus),
        enum_check("final_email_status", FinalEmailStatus),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    job_id: Mapped[uuid.UUID | None] = uuid_fk("mining_jobs.id", ondelete="SET NULL", nullable=True)
    company_id: Mapped[uuid.UUID] = uuid_fk("companies.id", ondelete="CASCADE")
    full_name: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    designation: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(100))
    seniority: Mapped[str | None] = mapped_column(String(50))
    role_category: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    linkedin_url: Mapped[str | None] = mapped_column(String(1000))
    facebook_url: Mapped[str | None] = mapped_column(String(1000))
    source_page: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(50))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    primary_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    enrichment_status: Mapped[str] = mapped_column(String(20), default=EnrichmentStatus.NOT_NEEDED)
    enrichment_provider: Mapped[str | None] = mapped_column(String(100))
    final_email_status: Mapped[str | None] = mapped_column(String(30))
    last_verified_at: Mapped[datetime | None]
    sales_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", ondelete="SET NULL", nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped["Company"] = relationship(back_populates="contacts")
    email_candidates: Mapped[list["EmailCandidate"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", passive_deletes=True
    )
    validation_checks: Mapped[list["ValidationCheck"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", passive_deletes=True
    )


class EmailCandidate(Base):
    __tablename__ = "email_candidates"

    id: Mapped[UUIDPk]
    contact_id: Mapped[uuid.UUID] = uuid_fk("contacts.id", ondelete="CASCADE")
    email: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    contact: Mapped[Contact] = relationship(back_populates="email_candidates")


class ValidationCheck(Base):
    __tablename__ = "validation_checks"
    __table_args__ = (
        enum_check("syntax_status", StageStatus),
        enum_check("disposable_status", StageStatus),
        enum_check("role_based_status", StageStatus),
        enum_check("mx_status", StageStatus),
        enum_check("millionverifier_status", MillionVerifierStatus),
        enum_check("final_status", FinalEmailStatus),
    )

    id: Mapped[UUIDPk]
    email_candidate_id: Mapped[uuid.UUID] = uuid_fk("email_candidates.id", ondelete="CASCADE")
    # Denormalized for pipeline queries and the Email_Validation sheet tab.
    contact_id: Mapped[uuid.UUID] = uuid_fk("contacts.id", ondelete="CASCADE")
    company_id: Mapped[uuid.UUID | None] = uuid_fk(
        "companies.id", ondelete="SET NULL", nullable=True, index=False
    )
    syntax_status: Mapped[str] = mapped_column(String(20), default=StageStatus.PENDING)
    disposable_status: Mapped[str] = mapped_column(String(20), default=StageStatus.PENDING)
    role_based_status: Mapped[str] = mapped_column(String(20), default=StageStatus.PENDING)
    mx_status: Mapped[str] = mapped_column(String(20), default=StageStatus.PENDING)
    llm_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    llm_reason: Mapped[str | None] = mapped_column(Text)
    millionverifier_status: Mapped[str | None] = mapped_column(String(20))
    final_status: Mapped[str | None] = mapped_column(String(30))
    final_reason: Mapped[str | None] = mapped_column(Text)
    raw_result_json: Mapped[dict | None] = mapped_column(JSONB)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    contact: Mapped[Contact] = relationship(back_populates="validation_checks")
    email_candidate: Mapped[EmailCandidate] = relationship()
