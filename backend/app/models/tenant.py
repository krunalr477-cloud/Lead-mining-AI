"""Tenant and user aggregates."""

import uuid
from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import Role
from app.db import Base, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

__all__ = ["Tenant", "User"]


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUIDPk]
    name: Mapped[str] = mapped_column(String(255))
    google_workspace_domain: Mapped[str | None] = mapped_column(String(255))
    google_spreadsheet_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    users: Mapped[list["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        enum_check("role", Role),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(32), default=Role.VIEWER)
    google_oauth_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="users")
