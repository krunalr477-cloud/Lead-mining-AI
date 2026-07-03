"""Unit tests for the real GoogleSheetsClient (Sheets v4) — NO live network.

The Google discovery service is faked by :class:`FakeService`, which mimics the
fluent ``service.spreadsheets().values().batchUpdate(body=...).execute()`` chain
and records every request body. Assertions target the exact request shapes:
addSheet calls, A1 ranges, deleteDimension indices, frozenRowCount +
setBasicFilter + conditional-format rules with the precise status hexes, and a
delete_rows remap that matches FakeSheetsClient row-for-row.

No test constructs real credentials or touches googleapiclient's transport: the
client is built with ``service=FakeService(...)`` injected, and _rate_limit is a
no-op because ``spreadsheet_id`` is preset (Redis is never contacted... unless a
test opts in; we monkeypatch it off to stay hermetic).
"""

from __future__ import annotations

import uuid

import pytest

from app.sheetsync.client import (
    FakeSheetsClient,
    GoogleSheetsClient,
    RangeUpdate,
    TabFormatting,
    _column_letter,
)

# --------------------------------------------------------------------------- #
# Fake googleapiclient discovery service.
# --------------------------------------------------------------------------- #


class _Request:
    """A pending API call: remembers verb + kwargs; runs a handler on execute()."""

    def __init__(self, handler, kwargs):
        self._handler = handler
        self.kwargs = kwargs

    def execute(self):
        return self._handler(self.kwargs)


class _Values:
    def __init__(self, service):
        self._s = service

    def update(self, **kwargs):
        self._s.calls.append(("values.update", kwargs))
        return _Request(self._s._on_values_update, kwargs)

    def batchUpdate(self, **kwargs):
        self._s.calls.append(("values.batchUpdate", kwargs))
        return _Request(self._s._on_values_batch_update, kwargs)

    def append(self, **kwargs):
        self._s.calls.append(("values.append", kwargs))
        return _Request(self._s._on_values_append, kwargs)

    def get(self, **kwargs):
        self._s.calls.append(("values.get", kwargs))
        return _Request(self._s._on_values_get, kwargs)


class _Spreadsheets:
    def __init__(self, service):
        self._s = service
        self._values = _Values(service)

    def values(self):
        return self._values

    def create(self, **kwargs):
        self._s.calls.append(("create", kwargs))
        return _Request(self._s._on_create, kwargs)

    def get(self, **kwargs):
        self._s.calls.append(("spreadsheets.get", kwargs))
        return _Request(self._s._on_get, kwargs)

    def batchUpdate(self, **kwargs):
        self._s.calls.append(("batchUpdate", kwargs))
        return _Request(self._s._on_batch_update, kwargs)


class FakeService:
    """In-memory Sheets backend behind the discovery fluent API.

    Storage: per tab, ``{"sheet_id": int, "rows": [[...], ...]}`` where row 0 is
    the header. This lets values.get/append/deleteDimension behave realistically
    so the client's row-number math is exercised end to end.
    """

    def __init__(self, spreadsheet_id="ss-1", sheets=None):
        self.spreadsheet_id = spreadsheet_id
        self._next_sheet_id = 1000
        self.tabs: dict[str, dict] = {}
        for name in sheets or []:
            self._add_sheet(name)
        self.calls: list[tuple[str, dict]] = []
        self.conditional_rules: dict[str, list[dict]] = {}
        self.frozen: dict[str, int] = {}
        self.filters: dict[str, dict] = {}

    # -- helpers -- #
    def _add_sheet(self, name):
        sid = self._next_sheet_id
        self._next_sheet_id += 1
        self.tabs[name] = {"sheet_id": sid, "rows": []}
        return sid

    def _tab_by_id(self, sheet_id):
        for name, t in self.tabs.items():
            if t["sheet_id"] == sheet_id:
                return name, t
        raise KeyError(sheet_id)

    def spreadsheets(self):
        return _Spreadsheets(self)

    # -- handlers -- #
    def _on_create(self, kwargs):
        body = kwargs["body"]
        title = body["properties"]["title"]
        self._add_sheet(title)  # a create yields one default sheet
        first = next(iter(self.tabs.values()))
        return {
            "spreadsheetId": self.spreadsheet_id,
            "sheets": [{"properties": {"sheetId": first["sheet_id"], "title": title}}],
        }

    def _on_get(self, kwargs):
        return {
            "sheets": [
                {"properties": {"sheetId": t["sheet_id"], "title": name}}
                for name, t in self.tabs.items()
            ]
        }

    def _on_batch_update(self, kwargs):
        replies = []
        for req in kwargs["body"]["requests"]:
            if "addSheet" in req:
                title = req["addSheet"]["properties"]["title"]
                sid = self._add_sheet(title)
                replies.append({"addSheet": {"properties": {"sheetId": sid, "title": title}}})
            elif "deleteDimension" in req:
                rng = req["deleteDimension"]["range"]
                _name, tab = self._tab_by_id(rng["sheetId"])
                del tab["rows"][rng["startIndex"] : rng["endIndex"]]
                replies.append({})
            elif "updateSheetProperties" in req:
                props = req["updateSheetProperties"]["properties"]
                name, _t = self._tab_by_id(props["sheetId"])
                self.frozen[name] = props["gridProperties"]["frozenRowCount"]
                replies.append({})
            elif "setBasicFilter" in req:
                rng = req["setBasicFilter"]["filter"]["range"]
                name, _t = self._tab_by_id(rng["sheetId"])
                self.filters[name] = rng
                replies.append({})
            elif "addConditionalFormatRule" in req:
                rule = req["addConditionalFormatRule"]["rule"]
                sid = rule["ranges"][0]["sheetId"]
                name, _t = self._tab_by_id(sid)
                self.conditional_rules.setdefault(name, []).append(rule)
                replies.append({})
            else:
                replies.append({})
        return {"replies": replies}

    def _range_tab(self, a1):
        # "'Tab'!A1:X1" -> "Tab"
        left = a1.split("!", 1)[0]
        return left.strip("'")

    def _on_values_update(self, kwargs):
        name = self._range_tab(kwargs["range"])
        tab = self.tabs[name]
        values = kwargs["body"]["values"]
        if not tab["rows"]:
            tab["rows"].append(list(values[0]))
        else:
            tab["rows"][0] = list(values[0])
        return {"updatedCells": len(values[0])}

    def _on_values_batch_update(self, kwargs):
        for entry in kwargs["body"]["data"]:
            name = self._range_tab(entry["range"])
            tab = self.tabs[name]
            # parse start row from "'Tab'!A5:C5"
            a1 = entry["range"].split("!", 1)[1]
            start = a1.split(":", 1)[0]
            start_col = "".join(c for c in start if c.isalpha())
            start_row = int("".join(c for c in start if c.isdigit()))
            col0 = _col_to_index(start_col)
            row_idx = start_row - 1
            while len(tab["rows"]) <= row_idx:
                tab["rows"].append([])
            row = tab["rows"][row_idx]
            new_vals = entry["values"][0]
            need = col0 + len(new_vals)
            while len(row) < need:
                row.append("")
            for i, v in enumerate(new_vals):
                row[col0 + i] = v
        return {}

    def _on_values_append(self, kwargs):
        name = self._range_tab(kwargs["range"])
        tab = self.tabs[name]
        values = kwargs["body"]["values"]
        first_new = len(tab["rows"]) + 1  # 1-based sheet row of first appended
        tab["rows"].extend(list(v) for v in values)
        last_new = len(tab["rows"])
        ncols = max((len(r) for r in tab["rows"]), default=1)
        last_col = _column_letter(max(0, ncols - 1))
        return {
            "updates": {
                "updatedRange": f"'{name}'!A{first_new}:{last_col}{last_new}",
                "updatedRows": len(values),
            }
        }

    def _on_values_get(self, kwargs):
        a1 = kwargs["range"]
        name = self._range_tab(a1)
        tab = self.tabs.get(name, {"rows": []})
        rows = tab["rows"]
        major = kwargs.get("majorDimension", "ROWS")
        body = a1.split("!", 1)[1]
        # Header-only "1:1"
        if body in ("1:1",):
            return {"values": [rows[0]] if rows else []}
        # Single-column key read "A2:A" (majorDimension=COLUMNS)
        if major == "COLUMNS":
            col_letter = "".join(c for c in body.split(":", 1)[0] if c.isalpha())
            col = _col_to_index(col_letter)
            data = rows[1:]  # skip header
            column = [(r[col] if col < len(r) else "") for r in data]
            return {"values": [column]}
        # Whole grid "A1:X"
        return {"values": [list(r) for r in rows]}


def _col_to_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Neutralise the Redis-backed rate limiter for every test."""
    monkeypatch.setattr(GoogleSheetsClient, "_rate_limit", lambda self: None)


TABS = [
    ("README", ["tab", "notes"]),
    ("Contacts", ["contact_id", "email", "final_email_status", "owner"]),
]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_column_letter():
    assert _column_letter(0) == "A"
    assert _column_letter(25) == "Z"
    assert _column_letter(26) == "AA"
    assert _column_letter(27) == "AB"
    assert _column_letter(701) == "ZZ"
    assert _column_letter(702) == "AAA"


def test_ensure_spreadsheet_create_when_no_id():
    svc = FakeService(spreadsheet_id="new-ss")
    client = GoogleSheetsClient(service=svc)  # no spreadsheet_id -> create
    tid = uuid.uuid4()
    ssid = client.ensure_spreadsheet(tid)
    assert ssid == "new-ss"
    assert any(verb == "create" for verb, _ in svc.calls)


def test_ensure_spreadsheet_attach_when_id_present():
    svc = FakeService(spreadsheet_id="ss-x", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-x")
    ssid = client.ensure_spreadsheet(uuid.uuid4())
    assert ssid == "ss-x"
    # Attach path issues a spreadsheets.get (no create).
    assert any(verb == "spreadsheets.get" for verb, _ in svc.calls)
    assert not any(verb == "create" for verb, _ in svc.calls)


def test_ensure_tabs_adds_missing_only():
    # README already exists; Contacts is missing -> exactly one addSheet.
    svc = FakeService(spreadsheet_id="ss-1", sheets=["README"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    client.ensure_tabs(TABS)

    add_calls = [k for v, k in svc.calls if v == "batchUpdate"]
    add_titles = [
        r["addSheet"]["properties"]["title"]
        for call in add_calls
        for r in call["body"]["requests"]
        if "addSheet" in r
    ]
    assert add_titles == ["Contacts"]
    # Header rows written for both tabs via values.batchUpdate.
    header_batch = [k for v, k in svc.calls if v == "values.batchUpdate"]
    assert header_batch, "expected a values.batchUpdate for header rows"
    ranges = {d["range"] for d in header_batch[-1]["body"]["data"]}
    assert "'README'!A1:B1" in ranges
    assert "'Contacts'!A1:D1" in ranges


def test_append_rows_returns_row_numbers_and_a1():
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    header = ["contact_id", "email", "final_email_status", "owner"]
    client.ensure_tabs([("Contacts", header)])  # writes header at row 1

    assigned = client.append_rows(
        "Contacts",
        header,
        [
            {"contact_id": "c1", "email": "a@x.com", "final_email_status": "verified"},
            {"contact_id": "c2", "email": "b@x.com", "final_email_status": "invalid"},
        ],
    )
    assert assigned == [2, 3]
    # Append target range is the header band (A1:D1).
    append_call = next(k for v, k in svc.calls if v == "values.append")
    assert append_call["range"] == "'Contacts'!A1:D1"
    # Missing columns become "".
    assert svc.tabs["Contacts"]["rows"][1] == ["c1", "a@x.com", "verified", ""]


def test_update_ranges_builds_contiguous_a1_runs():
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    header = ["contact_id", "email", "final_email_status", "owner"]
    client.ensure_tabs([("Contacts", header)])
    client.append_rows("Contacts", header, [{"contact_id": "c1"}])

    # Update non-adjacent columns: contact_id (A) and final_email_status (C).
    svc.calls.clear()
    client.update_ranges(
        "Contacts",
        header,
        [RangeUpdate(row_number=2, columns={"contact_id": "c1", "final_email_status": "verified"})],
    )
    batch = next(k for v, k in svc.calls if v == "values.batchUpdate")
    ranges = sorted(d["range"] for d in batch["body"]["data"])
    # A and C are non-contiguous -> two 1-wide ranges on row 2.
    assert ranges == ["'Contacts'!A2:A2", "'Contacts'!C2:C2"]


def test_update_ranges_merges_adjacent_columns():
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    header = ["contact_id", "email", "final_email_status", "owner"]
    client.ensure_tabs([("Contacts", header)])
    client.append_rows("Contacts", header, [{"contact_id": "c1"}])

    svc.calls.clear()
    client.update_ranges(
        "Contacts",
        header,
        [RangeUpdate(row_number=2, columns={"email": "z@x.com", "final_email_status": "verified"})],
    )
    batch = next(k for v, k in svc.calls if v == "values.batchUpdate")
    data = batch["body"]["data"]
    # email (B) + final_email_status (C) are adjacent -> ONE range B2:C2.
    assert [d["range"] for d in data] == ["'Contacts'!B2:C2"]
    assert data[0]["values"] == [["z@x.com", "verified"]]


def test_read_key_column():
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    header = ["contact_id", "email", "final_email_status", "owner"]
    client.ensure_tabs([("Contacts", header)])
    client.append_rows(
        "Contacts",
        header,
        [{"contact_id": "c1"}, {"contact_id": "c2"}, {"contact_id": "c3"}],
    )
    assert client.read_key_column("Contacts", "contact_id") == {"c1": 2, "c2": 3, "c3": 4}


def test_delete_rows_indices_and_remap_matches_fake():
    header = ["contact_id", "email", "final_email_status", "owner"]
    rows = [{"contact_id": f"c{i}"} for i in range(1, 6)]  # rows 2..6

    # Real client.
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    real = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    real.ensure_tabs([("Contacts", header)])
    real.append_rows("Contacts", header, rows)

    svc.calls.clear()
    real_remap = real.delete_rows("Contacts", [3, 5])  # delete c2 and c4

    # deleteDimension issued bottom-up with 0-based indices (row N -> [N-1, N)).
    del_call = next(k for v, k in svc.calls if v == "batchUpdate")
    idxs = [
        (r["deleteDimension"]["range"]["startIndex"], r["deleteDimension"]["range"]["endIndex"])
        for r in del_call["body"]["requests"]
    ]
    assert idxs == [(4, 5), (2, 3)]  # row 5 first, then row 3

    # Fake client remap for the identical operation.
    fake = FakeSheetsClient(uuid.uuid4(), persist=False)
    fake.ensure_tabs([("Contacts", header)])
    fake.append_rows("Contacts", header, [{c: r.get(c, "") for c in header} for r in rows])
    fake_remap = fake.delete_rows("Contacts", [3, 5])

    assert real_remap == fake_remap == {2: 2, 4: 3, 6: 4}


def test_apply_formatting_freeze_filter_and_status_hexes():
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    header = ["contact_id", "email", "final_email_status", "owner"]
    client.ensure_tabs([("Contacts", header)])

    fmt = TabFormatting(
        freeze_header=True,
        filter_enabled=True,
        status_columns={"final_email_status": "email_status"},
        status_colors={},
    )
    client.apply_formatting("Contacts", fmt)

    assert svc.frozen["Contacts"] == 1
    assert svc.filters["Contacts"]["endColumnIndex"] == 4

    rules = svc.conditional_rules["Contacts"]
    assert rules, "expected conditional-format rules"
    # Every rule targets the final_email_status column (index 2), data-only.
    for rule in rules:
        rng = rule["ranges"][0]
        assert rng["startColumnIndex"] == 2 and rng["endColumnIndex"] == 3
        assert rng["startRowIndex"] == 1  # header excluded

    # The exact status hexes must appear as background colors.
    def color_for(value):
        for rule in rules:
            vals = rule["booleanRule"]["condition"]["values"]
            if vals and vals[0]["userEnteredValue"] == value:
                c = rule["booleanRule"]["format"]["backgroundColor"]
                return _color_to_hex(c)
        return None

    assert color_for("verified") == "#00E69A"  # green
    assert color_for("invalid") == "#FF4D5E"  # red
    assert color_for("review") == "#F8C64E"  # amber
    assert color_for("risk") == "#9D7CFF"  # purple
    assert color_for("running") == "#61D7FF"  # cyan


def _color_to_hex(c: dict) -> str:
    r = round(c.get("red", 0.0) * 255)
    g = round(c.get("green", 0.0) * 255)
    b = round(c.get("blue", 0.0) * 255)
    return f"#{r:02X}{g:02X}{b:02X}"


def test_setup_end_to_end_idempotent_append():
    """A second append of the same content still returns fresh row numbers.

    (Engine-level idempotency is tested elsewhere; here we confirm the client's
    row-number accounting stays correct across two appends.)
    """
    svc = FakeService(spreadsheet_id="ss-1", sheets=["Contacts"])
    client = GoogleSheetsClient(service=svc, spreadsheet_id="ss-1")
    header = ["contact_id", "email", "final_email_status", "owner"]
    client.ensure_tabs([("Contacts", header)])
    first = client.append_rows("Contacts", header, [{"contact_id": "c1"}])
    second = client.append_rows("Contacts", header, [{"contact_id": "c2"}])
    assert first == [2]
    assert second == [3]
