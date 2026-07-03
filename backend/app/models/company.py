"""Company aggregate: companies, per-source evidence, hiring signals."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import AccessMethod, HiringSignalType, Posture
from app.db import Base, TimestampMixin, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

if TYPE_CHECKING:
    from app.models.contact import Contact

__all__ = ["Company", "CompanySource", "HiringSignal"]


class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_companies_tenant_id_domain", "tenant_id", "domain"),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    job_id: Mapped[uuid.UUID | None] = uuid_fk("mining_jobs.id", ondelete="SET NULL", nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(1000))
    domain: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    industry: Mapped[str | None] = mapped_column(String(255))
    services: Mapped[list[str]] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    company_size: Mapped[str | None] = mapped_column(String(50))
    google_place_id: Mapped[str | None] = mapped_column(String(255), index=True)
    google_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    google_reviews: Mapped[int | None] = mapped_column(Integer)
    facebook_page_url: Mapped[str | None] = mapped_column(String(1000))
    source_urls: Mapped[list[str]] = mapped_column(JSONB, default=list)
    dedupe_key: Mapped[str | None] = mapped_column(String(500), index=True)
    dedupe_status: Mapped[str] = mapped_column(String(50), default="unique")
    website_status: Mapped[str | None] = mapped_column(String(50))
    hiring_signal_status: Mapped[str | None] = mapped_column(String(50))
    # Worst-case posture across this company's sources (denormalized for the
    # Companies sheet tab, which requires a compliance_posture column).
    compliance_posture: Mapped[str | None] = mapped_column(String(10))
    last_refreshed_at: Mapped[datetime | None]

    sources: Mapped[list["CompanySource"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    hiring_signals: Mapped[list["HiringSignal"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )


class CompanySource(Base):
    __tablename__ = "company_sources"
    __table_args__ = (
        enum_check("access_method", AccessMethod),
        enum_check("compliance_posture", Posture),
    )

    id: Mapped[UUIDPk]
    company_id: Mapped[uuid.UUID] = uuid_fk("companies.id", ondelete="CASCADE")
    source_name: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(Text)
    access_method: Mapped[str] = mapped_column(String(30))
    compliance_posture: Mapped[str] = mapped_column(String(10))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="sources")


class HiringSignal(Base):
    __tablename__ = "hiring_signals"
    __table_args__ = (enum_check("signal_type", HiringSignalType),)

    id: Mapped[UUIDPk]
    company_id: Mapped[uuid.UUID] = uuid_fk("companies.id", ondelete="CASCADE")
    source: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(255))
    posted_at: Mapped[datetime | None]
    description_excerpt: Mapped[str | None] = mapped_column(Text)
    signal_type: Mapped[str] = mapped_column(String(30), default=HiringSignalType.JOB_POSTING)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="hiring_signals")
