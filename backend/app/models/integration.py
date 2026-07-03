"""Third-party integration credentials and metered API usage."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, utcnow
from app.models._shared import UUIDPk, uuid_fk

__all__ = ["APIUsage", "IntegrationCredential"]


class IntegrationCredential(TimestampMixin, Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (UniqueConstraint("tenant_id", "provider"),)

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE")
    provider: Mapped[str] = mapped_column(String(100))
    # Fernet-encrypted secret (or a reference to an external secret store entry).
    encrypted_secret_reference: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(50), default="active")
    last_verified_at: Mapped[datetime | None]


class APIUsage(Base):
    __tablename__ = "api_usage"
    __table_args__ = (Index("ix_api_usage_tenant_id_measured_at", "tenant_id", "measured_at"),)

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    provider: Mapped[str] = mapped_column(String(100))
    endpoint: Mapped[str] = mapped_column(String(255))
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    measured_at: Mapped[datetime] = mapped_column(default=utcnow)
