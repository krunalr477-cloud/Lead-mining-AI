"""Pluggable Sheets client interface + in-memory Fake backend (spec §5).

The engine talks only to :class:`SheetsClient`. In demo mode we run against
:class:`FakeSheetsClient`, an in-memory dict-of-tabs that:
- persists a JSON mirror to ``exports/sheets_mirror_{tenant}.json`` after writes,
- can dump an ``.xlsx`` via openpyxl for the "Open Sheet" / export affordance,
- records header freeze, filters, and status→color conditional formatting so a
  test can assert the formatting contract exists.

The real :class:`GoogleSheetsClient` drives the Sheets v4 API with tenant OAuth
credentials. It is selected by :mod:`app.sheetsync.factory` only when the tenant
has a stored Google credential and DEMO_MODE is off; otherwise the Fake backend
is used.
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
    def delete_rows(self, tab: str, row_numbers: Sequence[int]) -> dict[int, int]:
        """Delete data rows by 1-based row number.

        Deleting shifts lower rows up, so returns a ``{old_row_number:
        new_row_number}`` remap for the rows that survived, letting the caller
        keep its row-number index (SheetRowMap) consistent.
        """

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
        self.delete_count = 0

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

    def delete_rows(self, tab: str, row_numbers: Sequence[int]) -> dict[int, int]:
        store = self.tabs.get(tab)
        if store is None:
            return {}
        # Delete high indices first so earlier positions stay valid mid-loop.
        drop_idx = sorted({rn - 2 for rn in row_numbers}, reverse=True)
        for idx in drop_idx:
            if 0 <= idx < len(store["rows"]):
                del store["rows"][idx]
                self.delete_count += 1
        # Rebuild the old->new row-number remap for surviving rows.
        removed = {rn for rn in row_numbers}
        remap: dict[int, int] = {}
        new_rn = 2
        for old_rn in range(2, 2 + len(store["rows"]) + len(drop_idx)):
            if old_rn in removed:
                continue
            remap[old_rn] = new_rn
            new_rn += 1
        self._flush_json()
        return remap

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


# --------------------------------------------------------------------------- #
# Real Google Sheets backend (Sheets v4).
# --------------------------------------------------------------------------- #

# Status palette used by conditional-format rules (task spec / spec §5 §3).
# These are the sheet-cell colors; they may differ from the app-UI palette.
_STATUS_HEX: dict[str, str] = {
    "green": "#00E69A",  # verified / valid / delivered
    "red": "#FF4D5E",  # invalid / rejected / hard bounce
    "amber": "#F8C64E",  # review / catch-all / unknown
    "purple": "#9D7CFF",  # risk / low-confidence review
    "cyan": "#61D7FF",  # running / queued
}

# Which status *values* fall in each color bucket. Matched TEXT_EQ against the
# cell contents so a value like "verified" paints the whole cell green. Values
# are the lower-cased forms the engine writes into status columns.
_STATUS_BUCKETS: dict[str, tuple[str, ...]] = {
    "green": (
        "verified",
        "valid",
        "delivered",
        "sent",
        "opened",
        "replied",
        "completed",
        "pass",
    ),
    "red": (
        "invalid",
        "invalid_syntax",
        "provider_invalid",
        "disposable_rejected",
        "role_based_rejected",
        "mx_failed",
        "suppressed",
        "hard",
        "hard_bounce",
        "bounced",
        "blocked",
        "spam_complaint",
        "failed",
        "fail",
        "rejected",
    ),
    "amber": (
        "catch_all",
        "catch_all_review",
        "unknown",
        "unknown_retry",
        "review",
        "soft_bounce",
        "flagged",
    ),
    "purple": ("risk", "risk_review", "llm_low_confidence"),
    "cyan": ("running", "queued", "pending", "sending", "scheduled"),
}


def _column_letter(index: int) -> str:
    """0-based column index -> A1 column letters (0->A, 25->Z, 26->AA)."""
    if index < 0:
        raise ValueError(f"column index must be >= 0, got {index}")
    letters = ""
    n = index + 1  # shift to 1-based for the base-26 bijection
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _hex_to_color(hex_color: str) -> dict[str, float]:
    """'#RRGGBB' -> Sheets Color dict with 0..1 float channels."""
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return {"red": round(r, 6), "green": round(g, 6), "blue": round(b, 6)}


def _contiguous_runs(indices: Sequence[int]) -> list[tuple[int, int]]:
    """Collapse sorted 0-based column indices into (start, end_exclusive) runs."""
    runs: list[tuple[int, int]] = []
    for idx in sorted(indices):
        if runs and idx == runs[-1][1]:
            runs[-1] = (runs[-1][0], idx + 1)
        else:
            runs.append((idx, idx + 1))
    return runs


class GoogleSheetsClient(SheetsClient):
    """Real Google Sheets backend on the Sheets v4 API.

    Talks to ``spreadsheets`` and ``spreadsheets.values`` via the
    ``google-api-python-client`` discovery service. The constructor takes tenant
    OAuth credentials (a :class:`google.oauth2.credentials.Credentials`) or a
    zero-arg callable returning one, so a stored refresh token can be minted into
    an access token lazily.

    Quota: every mutating call is gated by a per-spreadsheet Redis token bucket
    (``rl:sheets:{spreadsheet_id}`` at ``settings.sheets_writes_per_minute``);
    a 429 from Google triggers a tenacity backoff retry.
    """

    def __init__(
        self,
        credentials: Any = None,
        *,
        spreadsheet_id: str | None = None,
        service: Any = None,
        title_prefix: str = "LeadMine",
    ) -> None:
        # ``credentials`` may be a Credentials object or a callable returning one.
        self._credentials = credentials
        self.spreadsheet_id = spreadsheet_id
        self.title_prefix = title_prefix
        self._service = service  # injectable for tests
        # tab name -> {"sheet_id": int, "header": list[str]}
        self._sheet_meta: dict[str, dict[str, Any]] = {}
        self._bucket = None

    # ---- service / credentials ------------------------------------------- #

    def _resolve_credentials(self) -> Any:
        creds = self._credentials
        if callable(creds):
            creds = creds()
        if creds is None:
            raise RuntimeError("GoogleSheetsClient requires OAuth credentials")
        return creds

    @property
    def service(self) -> Any:
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "sheets",
                "v4",
                credentials=self._resolve_credentials(),
                cache_discovery=False,
            )
        return self._service

    def _rate_limit(self) -> None:
        """Block-free debit of the per-spreadsheet write bucket (best effort)."""
        if self.spreadsheet_id is None:
            return
        if self._bucket is None:
            from app.config import get_settings
            from app.workers.rate_limit import TokenBucket, get_redis

            rpm = max(1, get_settings().sheets_writes_per_minute)
            try:
                self._bucket = TokenBucket(
                    get_redis(),
                    key=f"rl:sheets:{self.spreadsheet_id}",
                    rate=rpm,
                    per_seconds=60.0,
                    burst=rpm,
                )
            except Exception:  # Redis unavailable -> skip client-side limiting
                self._bucket = False  # sentinel: tried and failed
                return
        if self._bucket:
            self._bucket.acquire(1)

    # ---- lifecycle ------------------------------------------------------- #

    def ensure_spreadsheet(self, tenant_id: UUID) -> str:
        """Attach to ``spreadsheet_id`` if set, else create a new spreadsheet."""
        if self.spreadsheet_id:
            self._load_sheet_meta()
            return self.spreadsheet_id
        body = {"properties": {"title": f"{self.title_prefix} — {tenant_id}"}}
        created = self._execute(
            self.service.spreadsheets().create(body=body, fields="spreadsheetId,sheets.properties")
        )
        self.spreadsheet_id = created["spreadsheetId"]
        self._index_sheets(created.get("sheets", []))
        return self.spreadsheet_id

    def _load_sheet_meta(self) -> None:
        meta = self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets.properties",
            )
        )
        self._index_sheets(meta.get("sheets", []))

    def _conditional_rule_count(self, sheet_id: int) -> int:
        """Count existing conditional-format rules on a sheet, so they can be
        cleared before re-adding (rules aren't idempotent — re-running formatting
        would otherwise stack duplicate rules on every sync)."""
        meta = self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties.sheetId,conditionalFormats)",
            )
        )
        for sheet in meta.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == sheet_id:
                return len(sheet.get("conditionalFormats", []))
        return 0

    def _index_sheets(self, sheets: Sequence[dict]) -> None:
        for sheet in sheets:
            props = sheet.get("properties", {})
            title = props.get("title")
            if title is None:
                continue
            self._sheet_meta.setdefault(title, {})
            self._sheet_meta[title]["sheet_id"] = props.get("sheetId")

    def ensure_tabs(self, tabs: Sequence[tuple[str, Sequence[str]]]) -> None:
        """addSheet any missing tab, then (re)write every header row."""
        if not self._sheet_meta:
            self._load_sheet_meta()
        add_requests: list[dict] = []
        for name, _header in tabs:
            if name not in self._sheet_meta or "sheet_id" not in self._sheet_meta.get(name, {}):
                add_requests.append({"addSheet": {"properties": {"title": name}}})
        if add_requests:
            reply = self._execute(
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": add_requests},
                )
            )
            for r in reply.get("replies", []):
                props = r.get("addSheet", {}).get("properties", {})
                title = props.get("title")
                if title is not None:
                    self._sheet_meta.setdefault(title, {})
                    self._sheet_meta[title]["sheet_id"] = props.get("sheetId")

        # Header rows: one values.update per tab, batched into values.batchUpdate.
        data = []
        for name, header in tabs:
            self._sheet_meta.setdefault(name, {})["header"] = list(header)
            last_col = _column_letter(len(header) - 1) if header else "A"
            data.append(
                {
                    "range": f"'{name}'!A1:{last_col}1",
                    "values": [list(header)],
                }
            )
        if data:
            self._execute(
                self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": data},
                )
            )

        # Delete Google's auto-created "Sheet1" once real spec tabs exist, so the
        # workbook opens on a data tab instead of an empty default. Guard on there
        # being at least one other sheet (a spreadsheet must keep one).
        spec_names = {name for name, _ in tabs}
        default = self._sheet_meta.get("Sheet1")
        if (
            "Sheet1" not in spec_names
            and default
            and "sheet_id" in default
            and len(self._sheet_meta) > 1
        ):
            self._execute(
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": [{"deleteSheet": {"sheetId": default["sheet_id"]}}]},
                )
            )
            self._sheet_meta.pop("Sheet1", None)

    # ---- reads ----------------------------------------------------------- #

    def read_key_column(self, tab: str, key_column: str) -> dict[str, int]:
        """Return ``{row_key: 1-based row_number}`` from the key column."""
        header = self._header_for(tab)
        try:
            col_idx = header.index(key_column)
        except ValueError as exc:
            raise KeyError(f"{key_column!r} not in header for tab {tab!r}") from exc
        letter = _column_letter(col_idx)
        # Read from row 2 down (skip header).
        resp = self._execute(
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!{letter}2:{letter}",
                majorDimension="COLUMNS",
            )
        )
        values = resp.get("values", [])
        column = values[0] if values else []
        out: dict[str, int] = {}
        for i, key in enumerate(column):
            if key not in (None, ""):
                out[str(key)] = i + 2  # +2: header is row 1, data starts at row 2
        return out

    # ---- writes ---------------------------------------------------------- #

    def append_rows(self, tab: str, header: Sequence[str], rows: Sequence[dict]) -> list[int]:
        """Append rows in header order; return their assigned 1-based row numbers."""
        header = list(header)
        self._sheet_meta.setdefault(tab, {})["header"] = header
        if not rows:
            return []
        values = [[_cell(row.get(col, "")) for col in header] for row in rows]
        last_col = _column_letter(len(header) - 1) if header else "A"
        resp = self._execute(
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!A1:{last_col}1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                includeValuesInResponse=False,
                body={"values": values},
            )
        )
        # updatedRange like "'Tab'!A5:X7" -> first data row is 5.
        updated_range = resp.get("updates", {}).get("updatedRange", "")
        start_row = _first_row_of_range(updated_range)
        return [start_row + i for i in range(len(rows))]

    def update_ranges(
        self, tab: str, header: Sequence[str], updates: Sequence[RangeUpdate]
    ) -> None:
        """Write ONLY each update's named columns, batched into one call."""
        if not updates:
            return
        header = list(header)
        col_index = {name: i for i, name in enumerate(header)}
        data: list[dict] = []
        for upd in updates:
            # Group the update's named columns into contiguous A1 runs so each
            # run is a single ValueRange (fewer ranges, one batch call).
            named = {c: v for c, v in upd.columns.items() if c in col_index}
            by_idx = {col_index[c]: v for c, v in named.items()}
            for start, end in _contiguous_runs(sorted(by_idx)):
                row_values = [_cell(by_idx[i]) for i in range(start, end)]
                a1 = (
                    f"'{tab}'!{_column_letter(start)}{upd.row_number}"
                    f":{_column_letter(end - 1)}{upd.row_number}"
                )
                data.append({"range": a1, "values": [row_values]})
        if not data:
            return
        self._execute(
            self.service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
        )

    def delete_rows(self, tab: str, row_numbers: Sequence[int]) -> dict[int, int]:
        """deleteDimension each row bottom-up; return old->new survivor remap."""
        if not row_numbers:
            return {}
        sheet_id = self._sheet_id(tab)
        # Delete high row numbers first so lower indices stay valid mid-batch.
        drop_rows = sorted({int(rn) for rn in row_numbers}, reverse=True)
        requests = []
        for rn in drop_rows:
            # 1-based sheet row rn -> 0-based dimension index rn-1.
            requests.append(
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": rn - 1,
                            "endIndex": rn,
                        }
                    }
                }
            )
        self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            )
        )
        return self._remap_after_delete(tab, row_numbers)

    def _remap_after_delete(self, tab: str, row_numbers: Sequence[int]) -> dict[int, int]:
        """Old->new row-number remap for survivors (matches FakeSheetsClient).

        Every 1-based data row (2..last) that was not deleted is renumbered in
        order, closing the gaps the deletions left behind. The remap is over the
        PRE-delete row space, so we reconstruct the pre-delete last row from the
        (already compacted) post-delete grid count plus the number removed.
        """
        removed = {int(rn) for rn in row_numbers}
        # Row 1 is the header; the grid returned here is already compacted.
        surviving_data_rows = max(0, self._grid_row_count(tab) - 1)
        pre_delete_last_row = surviving_data_rows + len(removed) + 1
        remap: dict[int, int] = {}
        new_rn = 2
        for old_rn in range(2, pre_delete_last_row + 1):
            if old_rn in removed:
                continue
            remap[old_rn] = new_rn
            new_rn += 1
        return remap

    def _grid_row_count(self, tab: str) -> int:
        """Total rows currently present in the tab (header + data)."""
        header = self._header_for(tab)
        letter = _column_letter(max(0, len(header) - 1))
        resp = self._execute(
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!A1:{letter}",
            )
        )
        return len(resp.get("values", []))

    def apply_formatting(self, tab: str, formatting: TabFormatting) -> None:
        """Freeze header, set a basic filter, and color status columns."""
        header = formatting_header = self._header_for(tab)
        sheet_id = self._sheet_id(tab)
        col_count = max(1, len(header))
        requests: list[dict] = []

        if formatting.freeze_header:
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                }
            )

        if formatting.filter_enabled:
            requests.append(
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "startColumnIndex": 0,
                                "endColumnIndex": col_count,
                            }
                        }
                    }
                }
            )

        # Clear any conditional-format rules already on this sheet before re-adding,
        # so repeated syncs don't stack duplicate rules without bound. Deleting
        # index 0 N times drains all N (each delete shifts the rest down).
        if formatting.status_columns:
            existing_rules = self._conditional_rule_count(sheet_id)
            for _ in range(existing_rules):
                requests.append(
                    {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
                )

        # One conditional-format rule per (status column x color bucket).
        for column in formatting.status_columns:
            if column not in formatting_header:
                continue
            col_idx = formatting_header.index(column)
            for bucket, hex_color in _STATUS_HEX.items():
                values = _STATUS_BUCKETS.get(bucket, ())
                for value in values:
                    requests.append(
                        {
                            "addConditionalFormatRule": {
                                "rule": {
                                    "ranges": [
                                        {
                                            "sheetId": sheet_id,
                                            "startRowIndex": 1,  # skip header
                                            "startColumnIndex": col_idx,
                                            "endColumnIndex": col_idx + 1,
                                        }
                                    ],
                                    "booleanRule": {
                                        "condition": {
                                            "type": "TEXT_EQ",
                                            "values": [{"userEnteredValue": value}],
                                        },
                                        "format": {"backgroundColor": _hex_to_color(hex_color)},
                                    },
                                },
                                "index": 0,
                            }
                        }
                    )

        if requests:
            self._execute(
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests},
                )
            )

    # ---- internals ------------------------------------------------------- #

    def _header_for(self, tab: str) -> list[str]:
        meta = self._sheet_meta.get(tab)
        if meta and meta.get("header"):
            return meta["header"]
        # Fall back to reading row 1 from the sheet.
        resp = self._execute(
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"'{tab}'!1:1")
        )
        values = resp.get("values", [])
        header = [str(c) for c in values[0]] if values else []
        self._sheet_meta.setdefault(tab, {})["header"] = header
        return header

    def _sheet_id(self, tab: str) -> int:
        meta = self._sheet_meta.get(tab)
        if not meta or meta.get("sheet_id") is None:
            self._load_sheet_meta()
            meta = self._sheet_meta.get(tab)
        if not meta or meta.get("sheet_id") is None:
            raise KeyError(f"Unknown tab {tab!r} (no sheetId)")
        return int(meta["sheet_id"])

    def _execute(self, request: Any) -> Any:
        """Run a Google API request with a 429/5xx tenacity backoff retry."""
        from googleapiclient.errors import HttpError
        from tenacity import (
            retry,
            retry_if_exception,
            stop_after_attempt,
            wait_exponential,
        )

        def _is_rate_limited(exc: BaseException) -> bool:
            if isinstance(exc, HttpError):
                status = getattr(getattr(exc, "resp", None), "status", None)
                return status in (429, 500, 502, 503)
            return False

        @retry(
            retry=retry_if_exception(_is_rate_limited),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            stop=stop_after_attempt(5),
            reraise=True,
        )
        def _do() -> Any:
            # Gate every call (reads, creates, ensure_tabs, formatting) through the
            # token bucket — not just writes — so bursts of small reads/creates
            # can't trip Google's per-minute quota. Retries re-acquire, spacing
            # out backoff attempts too.
            self._rate_limit()
            return request.execute()

        return _do()


def _cell(value: Any) -> Any:
    """Coerce a value to a Sheets-writable scalar (str/int/float/bool)."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _first_row_of_range(a1_range: str) -> int:
    """Parse the first row number out of an A1 range like ``'Tab'!A5:X7`` -> 5."""
    if "!" in a1_range:
        a1_range = a1_range.split("!", 1)[1]
    start = a1_range.split(":", 1)[0]
    digits = "".join(ch for ch in start if ch.isdigit())
    return int(digits) if digits else 2
