"""Database engines and session factories.

Two engines, one metadata:
- async (asyncpg) for the FastAPI request path
- sync (psycopg) for Celery workers, Alembic, and scripts

Workers must NEVER import the async factory (ruff banned-api enforces this).
"""

import uuid
from datetime import UTC, datetime

import uuid_utils
from sqlalchemy import MetaData, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid7() -> uuid.UUID:
    """Time-ordered UUIDv7 primary keys (index-friendly)."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


settings = get_settings()

async_engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
sync_session_factory = sessionmaker(sync_engine, expire_on_commit=False)
