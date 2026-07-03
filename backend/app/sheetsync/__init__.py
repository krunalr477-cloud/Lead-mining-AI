"""Sheets sync engine (spec §5).

Mirrors PostgreSQL into a per-tenant Google Spreadsheet with 12 tabs. In demo
mode the real Google client is not wired: the engine runs against the pluggable
``SheetsClient`` interface with an in-memory ``FakeSheetsClient`` that persists a
JSON mirror to ``exports/`` and can dump an ``.xlsx`` for the "Open Sheet"
affordance. The real ``GoogleSheetsClient`` is a stub until Phase 3.

Public surface:
- ``TabSpec`` / ``TABS`` / ``TABS_BY_NAME`` — declarative tab definitions.
- ``SheetsClient`` / ``FakeSheetsClient`` / ``GoogleSheetsClient`` — clients.
- ``SheetSyncEngine`` — setup + idempotent per-tab flush.
- ``STATUS_COLORS`` — the status→color map applied as conditional formatting.
"""

from app.sheetsync.client import (
    FakeSheetsClient,
    GoogleSheetsClient,
    RangeUpdate,
    SheetsClient,
)
from app.sheetsync.engine import STATUS_COLORS, FlushResult, SheetSyncEngine
from app.sheetsync.tabs import TABS, TABS_BY_NAME, TabSpec

__all__ = [
    "STATUS_COLORS",
    "TABS",
    "TABS_BY_NAME",
    "FakeSheetsClient",
    "FlushResult",
    "GoogleSheetsClient",
    "RangeUpdate",
    "SheetSyncEngine",
    "SheetsClient",
    "TabSpec",
]
