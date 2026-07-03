"""Google Sheets sync bookkeeping: sync event log and row-position map."""

import uuid
from datetime import datetime

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import SyncStatus
from app.db import Base, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

__all__ = ["SheetRowMap", "SpreadsheetSyncEvent"]


class SpreadsheetSyncEvent(Base):
    __tablename__ = "spreadsheet_sync_events"
    __table_args__ = (
        Index("ix_spreadsheet_sync_events_tenant_id_created_at", "tenant_id", "created_at"),
        Index(
            "ix_spreadsheet_sync_events_tenant_id_sheet_tab_row_key",
            "tenant_id",
            "sheet_tab",
            "row_key",
        ),
        enum_check("status", SyncStatus),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    sheet_tab: Mapped[str] = mapped_column(String(100))
    row_key: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(20))  # upsert | delete | append
    status: Mapped[str] = mapped_column(String(20), default=SyncStatus.PENDING)
    error_message: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SheetRowMap(Base):
    __tablename__ = "sheet_row_maps"
    __table_args__ = (UniqueConstraint("tenant_id", "spreadsheet_id", "tab", "row_key"),)

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    spreadsheet_id: Mapped[str] = mapped_column(String(255))
    tab: Mapped[str] = mapped_column(String(100))
    row_key: Mapped[str] = mapped_column(String(255))
    row_number: Mapped[int] = mapped_column(Integer)
    # Hash of the last-written system-owned cells; skip no-op writes on sync.
    content_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
