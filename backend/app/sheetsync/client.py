"""Pluggable Sheets client interface + in-memory Fake backend (spec §5).

The engine talks only to :class:`SheetsClient`. In demo mode we run against
:class:`FakeSheetsClient`, an in-memory dict-of-tabs that:
- persists a JSON mirror to ``exports/sheets_mirror_{tenant}.json`` after writes,
- can dump an ``.xlsx`` via openpyxl for the "Open Sheet" / export affordance,
- records header freeze, filters, and status→color conditional formatting so a
  test can assert the formatting contract exists.

The real :class:`GoogleSheetsClient` is a stub raising ``NotImplementedError``
until Phase 3; it is registered here but unused in demo mode.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import REPO_ROOT

__all__ = [
    "FakeSheetsClient",
    "GoogleSheetsClient",
    "RangeUpdate",
    "SheetsClient",
    "TabFormatting",
]

EXPORTS_DIR = REPO_ROOT / "exports"


@dataclass(frozen=True)
class RangeUpdate:
    """A batched cell-range write: overwrite ``columns`` at 1-based ``row_number``.

    ``columns`` maps column name -> value. The client resolves column names to
    sheet cells using the tab header. Only the named columns are written, so the
    engine can push system columns while leaving editable columns untouched.
    """

    row_number: int
    columns: dict[str, Any]


@dataclass
class TabFormatting:
    """The formatting contract for one tab (recorded by the Fake client)."""

    freeze_header: bool = True
    filter_enabled: bool = True
    # column name -> status-rule key (e.g. "email_status"); rules resolve to
    # colors via the engine's STATUS_COLORS map.
    status_columns: dict[str, str] = field(default_factory=dict)
    # Flattened status value -> hex color, as recorded from the STATUS_COLORS map.
    status_colors: dict[str, str] = field(default_factory=dict)


class SheetsClient(ABC):
    """Backend-agnostic spreadsheet operations used by the sync engine."""

    @abstractmethod
    def ensure_spreadsheet(self, tenant_id: UUID) -> str:
        """Create/attach a spreadsheet for the tenant. Returns spreadsheet id."""

    @abstractmethod
    def ensure_tabs(self, tabs: Sequence[tuple[str, Sequence[str]]]) -> None:
        """Ensure each (tab_name, header_columns) exists with its header row."""

    @abstractmethod
    def read_key_column(self, tab: str, key_column: str) -> dict[str, int]:
        """Return ``{row_key: row_number}`` for existing data rows (1-based)."""

    @abstractmethod
    def append_rows(self, tab: str, header: Sequence[str], rows: Sequence[dict]) -> list[int]:
        """Append rows in header order. Returns the assigned 1-based row numbers."""

    @abstractmethod
    def update_ranges(
        self, tab: str, header: Sequence[str], updates: Sequence[RangeUpdate]
    ) -> None:
        """Apply partial-row updates, writing only each update's named columns."""

    @abstractmethod
    def apply_formatting(self, tab: str, formatting: TabFormatting) -> None:
        """Record/apply freeze, filters, and status colors for a tab."""


class FakeSheetsClient(SheetsClient):
    """In-memory mirror with JSON persistence and .xlsx dump (demo backend).

    Storage model per tab::

        {"header": [...], "rows": [{col: val, ...}, ...]}

    Row 1 is the header; data rows start at sheet row 2. A data row at list
    index ``i`` therefore lives at 1-based sheet row ``i + 2``.
    """

    #: Test hooks: total appended rows and total range updates since construction.
    def __init__(self, tenant_id: UUID | None = None, *, persist: bool = True) -> None:
        self.tenant_id = tenant_id
        self.persist = persist
        self.spreadsheet_id: str | None = None
        self.tabs: dict[str, dict[str, Any]] = {}
        self.formatting: dict[str, TabFormatting] = {}
        # Write counters — a test asserts these are 0 on an idempotent flush.
        self.append_count = 0
        self.update_count = 0

    # ---- lifecycle ------------------------------------------------------- #

    def ensure_spreadsheet(self, tenant_id: UUID) -> str:
        self.tenant_id = tenant_id
        if self.spreadsheet_id is None:
            self.spreadsheet_id = f"fake-sheet-{tenant_id}"
        return self.spreadsheet_id

    def ensure_tabs(self, tabs: Sequence[tuple[str, Sequence[str]]]) -> None:
        for name, header in tabs:
            if name not in self.tabs:
                self.tabs[name] = {"header": list(header), "rows": []}
            else:
                # Header is authoritative; refresh in case columns changed.
                self.tabs[name]["header"] = list(header)
        self._flush_json()

    # ---- reads ----------------------------------------------------------- #

    def read_key_column(self, tab: str, key_column: str) -> dict[str, int]:
        store = self.tabs.get(tab)
        if store is None:
            return {}
        out: dict[str, int] = {}
        for i, row in enumerate(store["rows"]):
            key = row.get(key_column)
            if key not in (None, ""):
                out[str(key)] = i + 2  # +2: skip header (row 1), 1-based rows
        return out

    # ---- writes ---------------------------------------------------------- #

    def append_rows(self, tab: str, header: Sequence[str], rows: Sequence[dict]) -> list[int]:
        store = self.tabs.setdefault(tab, {"header": list(header), "rows": []})
        assigned: list[int] = []
        for row in rows:
            full = {col: row.get(col, "") for col in header}
            store["rows"].append(full)
            assigned.append(len(store["rows"]) + 1)  # 1-based, header at row 1
            self.append_count += 1
        self._flush_json()
        return assigned

    def update_ranges(
        self, tab: str, header: Sequence[str], updates: Sequence[RangeUpdate]
    ) -> None:
        store = self.tabs.get(tab)
        if store is None:
            raise KeyError(f"Cannot update unknown tab {tab!r}")
        for upd in updates:
            idx = upd.row_number - 2  # invert append_rows' mapping
            if idx < 0 or idx >= len(store["rows"]):
                raise IndexError(f"row {upd.row_number} out of range for tab {tab!r}")
            target = store["rows"][idx]
            # Write ONLY the named columns — editable columns are never included
            # by the engine, so they survive untouched here.
            for col, val in upd.columns.items():
                target[col] = val
            self.update_count += 1
        self._flush_json()

    def apply_formatting(self, tab: str, formatting: TabFormatting) -> None:
        self.formatting[tab] = formatting
        self._flush_json()

    # ---- persistence ----------------------------------------------------- #

    def mirror_path(self) -> Path:
        return EXPORTS_DIR / f"sheets_mirror_{self.tenant_id}.json"

    def _flush_json(self) -> None:
        if not self.persist or self.tenant_id is None:
            return
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "spreadsheet_id": self.spreadsheet_id,
            "tenant_id": str(self.tenant_id),
            "tabs": self.tabs,
            "formatting": {
                name: {
                    "freeze_header": f.freeze_header,
                    "filter_enabled": f.filter_enabled,
                    "status_columns": f.status_columns,
                    "status_colors": f.status_colors,
                }
                for name, f in self.formatting.items()
            },
        }
        self.mirror_path().write_text(json.dumps(payload, indent=2, default=str))

    def dump_xlsx(self, path: Path | None = None) -> Path:
        """Write the in-memory mirror to an .xlsx (one sheet per tab).

        Backs the "Open Sheet" / XLSX-export affordance on the Sync Monitor.
        """
        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)  # drop the default empty sheet
        for name, store in self.tabs.items():
            # Excel sheet titles are capped at 31 chars.
            ws = wb.create_sheet(title=name[:31])
            header = store["header"]
            ws.append(list(header))
            ws.freeze_panes = "A2"  # freeze header row
            if header:
                ws.auto_filter.ref = ws.dimensions or "A1"
            for row in store["rows"]:
                ws.append([_xlsx_cell(row.get(col, "")) for col in header])
        if path is None:
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            path = EXPORTS_DIR / f"sheets_mirror_{self.tenant_id}.xlsx"
        wb.save(path)
        return path

    @classmethod
    def load(cls, tenant_id: UUID) -> FakeSheetsClient:
        """Rehydrate a Fake client from its JSON mirror (or empty if absent)."""
        client = cls(tenant_id)
        path = client.mirror_path()
        if path.exists():
            data = json.loads(path.read_text())
            client.spreadsheet_id = data.get("spreadsheet_id")
            client.tabs = data.get("tabs", {})
            for name, f in data.get("formatting", {}).items():
                client.formatting[name] = TabFormatting(**f)
        return client


def _xlsx_cell(value: Any) -> Any:
    """openpyxl accepts str/int/float/bool/None; coerce anything else to str."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class GoogleSheetsClient(SheetsClient):
    """Real Google Sheets backend — wired in Phase 3. Unused in demo mode."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Constructing is allowed (registration/DI); operations are not yet.
        self._args = args
        self._kwargs = kwargs

    def ensure_spreadsheet(self, tenant_id: UUID) -> str:
        raise NotImplementedError("wired in Phase 3")

    def ensure_tabs(self, tabs: Sequence[tuple[str, Sequence[str]]]) -> None:
        raise NotImplementedError("wired in Phase 3")

    def read_key_column(self, tab: str, key_column: str) -> dict[str, int]:
        raise NotImplementedError("wired in Phase 3")

    def append_rows(self, tab: str, header: Sequence[str], rows: Sequence[dict]) -> list[int]:
        raise NotImplementedError("wired in Phase 3")

    def update_ranges(
        self, tab: str, header: Sequence[str], updates: Sequence[RangeUpdate]
    ) -> None:
        raise NotImplementedError("wired in Phase 3")

    def apply_formatting(self, tab: str, formatting: TabFormatting) -> None:
        raise NotImplementedError("wired in Phase 3")
