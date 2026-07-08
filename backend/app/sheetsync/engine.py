"""Idempotent DB→Sheets sync engine (spec §5).

``SheetSyncEngine`` owns the diff logic that keeps a tenant's spreadsheet in sync
with PostgreSQL while never clobbering sales-edited cells:

setup_spreadsheet
    Ensure the spreadsheet + all 12 tabs + headers + per-tab formatting exist.

flush_tab
    Drain pending ``SpreadsheetSyncEvent`` rows for a tab, load current DB rows
    via ``TabSpec.source``, hash each row's *system-owned* columns, diff against
    ``SheetRowMap``, and:
      - append new keys (recording their row_number in SheetRowMap),
      - update changed keys writing ONLY system columns (editable columns are
        excluded from both the write and the hash, so a sales edit is invisible
        to the engine),
      - skip unchanged keys.
    A second flush with no DB change performs zero appends and zero updates.

enqueue_upsert
    Insert a pending ``SpreadsheetSyncEvent`` (called by pipeline code).

Idempotency rests on ``content_hash``: the SHA-256 of the canonical
system-column projection. Equal hash ⇒ no write. Editable-field protection rests
on two facts: (1) editable columns are excluded from the hash so they never
trigger an update, and (2) update payloads contain only system columns so the
client never overwrites an editable cell.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    CampaignStatus,
    FinalEmailStatus,
    JobStatus,
    MessageStatus,
    MillionVerifierStatus,
    SourceRunStatus,
    StageStatus,
    SyncStatus,
)
from app.db import utcnow
from app.models import SheetRowMap, SpreadsheetSyncEvent
from app.sheetsync.client import RangeUpdate, SheetsClient, TabFormatting
from app.sheetsync.tabs import TABS, TABS_BY_NAME, TabSpec

__all__ = ["STATUS_COLORS", "FlushResult", "SheetSyncEngine"]

# Status palette (spec §5 lines 452-456).
GREEN = "#00E69A"  # verified / valid / delivered
RED = "#FF4D5E"  # invalid / rejected / hard bounce
AMBER = "#FFB020"  # review / catch-all / unknown
PURPLE = "#A66BFF"  # alt for review / risk
CYAN = "#22D3EE"  # running / queued

# Flattened status-value -> color. The Fake client records this map so a test
# can assert the coloring contract exists (green/red/amber-purple/cyan buckets).
STATUS_COLORS: dict[str, str] = {
    # Green: good terminal states.
    FinalEmailStatus.VERIFIED: GREEN,
    MillionVerifierStatus.VALID: GREEN,
    MessageStatus.DELIVERED: GREEN,
    MessageStatus.SENT: GREEN,
    MessageStatus.OPENED: GREEN,
    MessageStatus.REPLIED: GREEN,
    CampaignStatus.COMPLETED: GREEN,
    JobStatus.COMPLETED: GREEN,
    SourceRunStatus.COMPLETED: GREEN,
    StageStatus.PASS: GREEN,
    "valid": GREEN,
    "delivered": GREEN,
    # Red: hard failures / rejections.
    FinalEmailStatus.INVALID_SYNTAX: RED,
    FinalEmailStatus.PROVIDER_INVALID: RED,
    FinalEmailStatus.DISPOSABLE_REJECTED: RED,
    FinalEmailStatus.ROLE_BASED_REJECTED: RED,
    FinalEmailStatus.MX_FAILED: RED,
    FinalEmailStatus.SUPPRESSED: RED,
    MillionVerifierStatus.INVALID: RED,
    MessageStatus.HARD_BOUNCE: RED,
    MessageStatus.BLOCKED: RED,
    MessageStatus.SPAM_COMPLAINT: RED,
    CampaignStatus.FAILED: RED,
    JobStatus.FAILED: RED,
    SourceRunStatus.FAILED: RED,
    StageStatus.FAIL: RED,
    "invalid": RED,
    "hard": RED,
    "hard_bounce": RED,
    "bounced": RED,
    # Amber: review / uncertain.
    FinalEmailStatus.CATCH_ALL_REVIEW: AMBER,
    FinalEmailStatus.UNKNOWN_RETRY: AMBER,
    MillionVerifierStatus.CATCH_ALL: AMBER,
    MillionVerifierStatus.UNKNOWN: AMBER,
    MessageStatus.SOFT_BOUNCE: AMBER,
    StageStatus.REVIEW: AMBER,
    "catch_all": AMBER,
    "unknown": AMBER,
    "review": AMBER,
    # Purple: risk / low-confidence review.
    FinalEmailStatus.RISK_REVIEW: PURPLE,
    FinalEmailStatus.LLM_LOW_CONFIDENCE: PURPLE,
    MillionVerifierStatus.RISK: PURPLE,
    "risk": PURPLE,
    # Cyan: in-flight.
    JobStatus.RUNNING: CYAN,
    JobStatus.QUEUED: CYAN,
    SourceRunStatus.RUNNING: CYAN,
    SourceRunStatus.PENDING: CYAN,
    CampaignStatus.SENDING: CYAN,
    CampaignStatus.QUEUED: CYAN,
    CampaignStatus.SCHEDULED: CYAN,
    MessageStatus.QUEUED: CYAN,
    "running": CYAN,
    "queued": CYAN,
}


@dataclass
class FlushResult:
    """Outcome of one ``flush_tab`` call — used by tests and the Sync Monitor."""

    tab: str
    appended: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    events_synced: int = 0
    events_failed: int = 0

    @property
    def writes(self) -> int:
        """Total mutating operations (0 ⇒ the flush was a no-op)."""
        return self.appended + self.updated + self.deleted


def _hash_row(content_row: dict) -> str:
    """SHA-256 over a canonical JSON encoding of the system-column projection."""
    canonical = json.dumps(content_row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class SheetSyncEngine:
    def __init__(self, session: Session, client: SheetsClient) -> None:
        self.session = session
        self.client = client
        self._spreadsheet_id: str | None = None

    # ---- setup ----------------------------------------------------------- #

    def setup_spreadsheet(self, tenant_id: UUID) -> str:
        """Ensure spreadsheet + 12 tabs + headers + formatting. Idempotent."""
        spreadsheet_id = self.client.ensure_spreadsheet(tenant_id)
        self._spreadsheet_id = spreadsheet_id
        self.client.ensure_tabs([(tab.name, tab.columns) for tab in TABS])
        for tab in TABS:
            self.client.apply_formatting(tab.name, self._formatting_for(tab))
        return spreadsheet_id

    @staticmethod
    def _formatting_for(tab: TabSpec) -> TabFormatting:
        # Record, for each status column, the value->color subset that applies
        # (best-effort: we surface the full palette buckets the tab can hit).
        colors = dict(STATUS_COLORS) if tab.status_columns else {}
        return TabFormatting(
            freeze_header=True,
            filter_enabled=True,
            status_columns=dict(tab.status_columns),
            status_colors=colors,
        )

    # ---- enqueue --------------------------------------------------------- #

    def enqueue_upsert(
        self, session: Session, tenant_id: UUID, tab: str, row_key: str
    ) -> SpreadsheetSyncEvent:
        """Insert a pending upsert event for ``(tab, row_key)`` (pipeline hook)."""
        if tab not in TABS_BY_NAME:
            raise ValueError(f"Unknown tab {tab!r}")
        event = SpreadsheetSyncEvent(
            tenant_id=tenant_id,
            sheet_tab=tab,
            row_key=str(row_key),
            operation="upsert",
            status=SyncStatus.PENDING,
        )
        session.add(event)
        session.flush()
        return event

    # ---- flush ----------------------------------------------------------- #

    def flush_tab(self, tenant_id: UUID, tab_name: str) -> FlushResult:
        """Reconcile one tab from the DB into the sheet. Idempotent per row."""
        spec = TABS_BY_NAME[tab_name]
        result = FlushResult(tab=tab_name)
        spreadsheet_id = self._resolve_spreadsheet_id(tenant_id)

        # Drain pending events up front so they get resolved even if a row later
        # disappears from the source (they're keyed by row_key, not row content).
        pending = self.session.scalars(
            select(SpreadsheetSyncEvent).where(
                SpreadsheetSyncEvent.tenant_id == tenant_id,
                SpreadsheetSyncEvent.sheet_tab == tab_name,
                SpreadsheetSyncEvent.status == SyncStatus.PENDING,
            )
        ).all()

        try:
            db_rows = spec.source(self.session, tenant_id)
        except Exception as exc:  # source failure fails every pending event
            for ev in pending:
                ev.status = SyncStatus.FAILED
                ev.error_message = str(exc)[:1000]
                result.events_failed += 1
            self.session.flush()
            raise

        # Existing row-position map for this tab.
        maps = self.session.scalars(
            select(SheetRowMap).where(
                SheetRowMap.tenant_id == tenant_id,
                SheetRowMap.spreadsheet_id == spreadsheet_id,
                SheetRowMap.tab == tab_name,
            )
        ).all()
        by_key: dict[str, SheetRowMap] = {m.row_key: m for m in maps}

        # Reconcile against the actual sheet when the row-map is empty. A sync that
        # appended rows to Google Sheets but crashed before committing SheetRowMap
        # (e.g. a 403 on a later tab) would otherwise re-append EVERY row as a
        # duplicate on the next run. Seed positions from the sheet's key column so
        # those rows are UPDATE-matched, not re-appended (empty hash forces one
        # corrective system-column write).
        if not by_key:
            for existing_key, row_number in self.client.read_key_column(
                tab_name, spec.key_column
            ).items():
                if existing_key and str(existing_key) not in by_key:
                    m = SheetRowMap(
                        tenant_id=tenant_id,
                        spreadsheet_id=spreadsheet_id,
                        tab=tab_name,
                        row_key=str(existing_key),
                        row_number=row_number,
                        content_hash="",
                    )
                    self.session.add(m)
                    by_key[str(existing_key)] = m

        to_append: list[tuple[str, dict, str]] = []  # (key, full_row, hash)
        updates: list[RangeUpdate] = []
        update_hashes: dict[str, str] = {}  # key -> new hash (by row_number)
        seen_keys: set[str] = set()

        for row in db_rows:
            key = spec.project(row).get(spec.key_column)
            if key in (None, ""):
                continue
            key = str(key)
            seen_keys.add(key)
            content_hash = _hash_row(spec.content_row(row))
            existing = by_key.get(key)
            if existing is None:
                to_append.append((key, spec.project(row), content_hash))
            elif existing.content_hash != content_hash:
                # Push ONLY system columns — editable columns are never included,
                # so sales-edited cells in the sheet are preserved.
                system_cols = {
                    c: scalar
                    for c, scalar in spec.project(row).items()
                    if c in set(spec.system_columns())
                }
                updates.append(RangeUpdate(row_number=existing.row_number, columns=system_cols))
                update_hashes[key] = content_hash
            else:
                result.skipped += 1

        # Order matters: updates (on current row numbers) -> deletions (shift
        # rows, remap survivors) -> appends (land at the end of the shortened
        # list). Doing appends first would leave their recorded row numbers stale
        # after a same-flush deletion shifted the list.

        # 1. Apply updates on existing rows, then refresh each changed hash.
        if updates:
            self.client.update_ranges(tab_name, spec.columns, updates)
            row_to_key = {m.row_number: m.row_key for m in maps}
            for upd in updates:
                key = row_to_key.get(upd.row_number)
                if key is not None:
                    by_key[key].content_hash = update_hashes[key]
                    by_key[key].updated_at = utcnow()
                    result.updated += 1

        # 2. Reconcile deletions: keys mapped in the sheet but no longer in the
        # source (e.g. a Sales_Ready lead tombstoned after a bounce) must be
        # REMOVED from the tab — otherwise the clean output leaks bounced/
        # suppressed rows (spec §5 / §25). Delete their rows and drop their maps,
        # then apply the client's row-number remap to the survivors.
        stale = [m for m in maps if m.row_key not in seen_keys]
        if stale:
            remap = self.client.delete_rows(tab_name, [m.row_number for m in stale])
            stale_keys = {m.row_key for m in stale}
            for m in maps:
                if m.row_key in stale_keys:
                    self.session.delete(m)
                elif m.row_number in remap:
                    m.row_number = remap[m.row_number]
            result.deleted += len(stale)

        # 3. Apply appends last, recording each new row_number in SheetRowMap.
        if to_append:
            assigned = self.client.append_rows(
                tab_name, spec.columns, [full for _, full, _ in to_append]
            )
            for (key, _full, content_hash), row_number in zip(to_append, assigned, strict=True):
                self.session.add(
                    SheetRowMap(
                        tenant_id=tenant_id,
                        spreadsheet_id=spreadsheet_id,
                        tab=tab_name,
                        row_key=key,
                        row_number=row_number,
                        content_hash=content_hash,
                    )
                )
                result.appended += 1

        # Resolve pending events: every pending event for this tab is now
        # reconciled — its key was appended, updated, unchanged, or deleted.
        now = utcnow()
        for ev in pending:
            ev.status = SyncStatus.SYNCED
            ev.synced_at = now
            result.events_synced += 1

        self.session.flush()
        return result

    def flush_all(self, tenant_id: UUID) -> list[FlushResult]:
        """Flush every tab, README included — its rows are static documentation
        produced by ``_readme_source`` and reconciled idempotently by key."""
        return [self.flush_tab(tenant_id, tab.name) for tab in TABS]

    # ---- helpers --------------------------------------------------------- #

    def _resolve_spreadsheet_id(self, tenant_id: UUID) -> str:
        if self._spreadsheet_id is None:
            self._spreadsheet_id = self.client.ensure_spreadsheet(tenant_id)
        return self._spreadsheet_id
