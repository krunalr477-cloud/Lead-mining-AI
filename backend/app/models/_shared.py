"""Internal column helpers shared across model modules. Not re-exported."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from sqlalchemy import CheckConstraint, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, uuid7

# utcnow() (used by TimestampMixin and all *_at defaults) returns timezone-aware
# datetimes, so every Mapped[datetime] column must be TIMESTAMPTZ — including the
# mixin columns declared in app.db, which resolve their type here at class-creation
# time via the registry.
Base.registry.update_type_annotation_map({datetime: DateTime(timezone=True)})

UUIDPk = Annotated[
    uuid.UUID,
    mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7),
]


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """VARCHAR + CHECK constraint instead of a Postgres ENUM type.

    NULL passes the check, so nullable status columns stay valid.
    """
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_valid")


def uuid_fk(
    target: str,
    *,
    ondelete: str,
    nullable: bool = False,
    index: bool = True,
    unique: bool = False,
) -> Mapped[uuid.UUID]:
    """UUID foreign-key column. CASCADE for owned children, SET NULL for soft refs."""
    return mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
        unique=unique,
    )
