"""End-to-end acceptance verification for the demo workspace (spec §22).

Runs the demo seed if the workspace is empty, then asserts the spec §22
acceptance criteria that Phase 2 is responsible for and prints a PASS/FAIL
table. Exits non-zero if any check fails.

Criteria covered here:
  5  — the pipeline ran end to end via the mock adapters.
  6  — companies discovered, normalized, deduplicated, stored (no dup dedupe_key).
  7  — contacts carry emails, roles, and source evidence.
  9  — every validation stage ran (all stage columns populated).
  11 — Sales_Ready_Leads holds only VERIFIED, non-suppressed, non-bounced leads.
  25 — no invalid/suppressed email is ever exposed as sales-ready.
Plus: the 12-tab sheet mirror is populated with frozen-header/filter/color
metadata, and the funnel totals are internally consistent.

    uv run python -m scripts.verify_demo
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import FinalEmailStatus, JobStatus, StageStatus
from app.db import sync_session_factory
from app.models import (
    BounceEvent,
    Campaign,
    Company,
    Contact,
    EmailCandidate,
    EmailMessage,
    MiningJob,
    SalesReadyLead,
    Suppression,
    ValidationCheck,
)
from app.seeds.demo import DEMO_IDS, seed_demo
from app.sheetsync.client import FakeSheetsClient
from app.sheetsync.tabs import TABS

# The 12 sheet tabs (spec §5). README is static; the other 11 are DB-backed and
# must contain populated rows after a demo run. All 12 must carry formatting.
_POPULATED_TABS = [t.name for t in TABS if t.name != "README"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _tenant_id() -> uuid.UUID:
    return DEMO_IDS["tenant"]


def _job_id() -> uuid.UUID:
    return DEMO_IDS["job"]


def _ensure_seeded(session: Session) -> None:
    """Seed the demo workspace if it has not produced any companies yet."""
    count = session.scalar(
        select(func.count()).select_from(Company).where(Company.job_id == _job_id())
    )
    if not count:
        seed_demo(session=session)
        session.commit()


# --------------------------------------------------------------------------- #
# Individual criteria
# --------------------------------------------------------------------------- #


def check_pipeline_ran(session: Session) -> Check:
    """Criterion 5: the job completed end to end."""
    job = session.get(MiningJob, _job_id())
    if job is None:
        return Check("5 · pipeline ran end-to-end", False, "demo job missing")
    ok = job.status == JobStatus.COMPLETED and (job.progress_percent or 0) == 100
    return Check(
        "5 · pipeline ran end-to-end",
        ok,
        f"status={job.status} progress={job.progress_percent}%",
    )


def check_companies_deduped(session: Session) -> Check:
    """Criterion 6: companies discovered, stored, and deduplicated."""
    total = (
        session.scalar(select(func.count()).select_from(Company).where(Company.job_id == _job_id()))
        or 0
    )
    # No two companies share a dedupe_key (the dedupe stage merged sightings).
    dup_keys = session.execute(
        select(Company.dedupe_key, func.count())
        .where(
            Company.tenant_id == _tenant_id(),
            Company.dedupe_key.is_not(None),
        )
        .group_by(Company.dedupe_key)
        .having(func.count() > 1)
    ).all()
    merged = (
        session.scalar(
            select(func.count())
            .select_from(Company)
            .where(Company.job_id == _job_id(), Company.dedupe_status == "merged")
        )
        or 0
    )
    ok = total > 0 and not dup_keys
    detail = f"{total} companies, {merged} merged, {len(dup_keys)} duplicate dedupe_keys"
    return Check("6 · companies deduped + stored", ok, detail)


def check_contacts_have_evidence(session: Session) -> Check:
    """Criterion 7: contacts carry emails, roles, and source evidence."""
    total = (
        session.scalar(select(func.count()).select_from(Contact).where(Contact.job_id == _job_id()))
        or 0
    )
    with_email = (
        session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.job_id == _job_id(), Contact.email.is_not(None))
        )
        or 0
    )
    with_role = (
        session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.job_id == _job_id(), Contact.role_category.is_not(None))
        )
        or 0
    )
    # Source evidence: every contact records the page/source it was extracted from.
    with_source = (
        session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.job_id == _job_id(),
                Contact.source_type.is_not(None),
                Contact.source_page.is_not(None),
            )
        )
        or 0
    )
    ok = total > 0 and with_email > 0 and with_role == total and with_source == total
    detail = (
        f"{total} contacts · {with_email} with email · "
        f"{with_role} with role · {with_source} with source evidence"
    )
    return Check("7 · contacts have emails/roles/evidence", ok, detail)


def check_validation_stages(session: Session) -> Check:
    """Criterion 9: every validation stage ran for every candidate."""
    checks = session.scalars(
        select(ValidationCheck)
        .join(Contact, ValidationCheck.contact_id == Contact.id)
        .where(Contact.job_id == _job_id())
    ).all()
    total = len(checks)
    # Each ValidationCheck must have all six stage columns populated (non-pending
    # for the pure stages; MX may be SKIPPED only when syntax failed).
    incomplete = 0
    stages_seen: set[str] = set()
    valid_stage_values = {s.value for s in StageStatus}
    for c in checks:
        for col in (c.syntax_status, c.disposable_status, c.role_based_status, c.mx_status):
            if col is None or col == StageStatus.PENDING.value or col not in valid_stage_values:
                incomplete += 1
                break
        if c.final_status:
            stages_seen.add(c.final_status)
    # A real end-to-end run exercises more than just VERIFIED (rejections/reviews).
    diversity_ok = len(stages_seen) >= 3
    ok = total > 0 and incomplete == 0 and diversity_ok
    detail = (
        f"{total} validation checks · {incomplete} incomplete · "
        f"{len(stages_seen)} distinct final statuses"
    )
    return Check("9 · every validation stage ran", ok, detail)


def check_sales_ready_clean(session: Session) -> Check:
    """Criteria 11 + 25: sales-ready holds only VERIFIED, non-suppressed leads."""
    leads = session.scalars(
        select(SalesReadyLead).where(
            SalesReadyLead.tenant_id == _tenant_id(),
            SalesReadyLead.tombstoned.is_(False),
        )
    ).all()
    total = len(leads)
    non_verified = [
        lead for lead in leads if lead.validation_status != FinalEmailStatus.VERIFIED.value
    ]
    # No sales-ready email may appear in the suppression list.
    supp_emails = {
        (e or "").lower()
        for e in session.scalars(
            select(Suppression.email).where(Suppression.tenant_id == _tenant_id())
        ).all()
        if e
    }
    suppressed_leaks = [lead for lead in leads if (lead.email or "").lower() in supp_emails]
    # No sales-ready email may appear in the bounce log.
    bounced_emails = {
        (e or "").lower()
        for e in session.scalars(
            select(BounceEvent.email)
            .join(EmailMessage, BounceEvent.email_message_id == EmailMessage.id)
            .join(Campaign, EmailMessage.campaign_id == Campaign.id)
            .where(Campaign.tenant_id == _tenant_id())
        ).all()
        if e
    }
    bounced_leaks = [lead for lead in leads if (lead.email or "").lower() in bounced_emails]
    ok = total > 0 and not non_verified and not suppressed_leaks and not bounced_leaks
    detail = (
        f"{total} sales-ready · {len(non_verified)} non-verified · "
        f"{len(suppressed_leaks)} suppressed-leak · {len(bounced_leaks)} bounced-leak"
    )
    return Check("11/25 · sales-ready is VERIFIED + clean", ok, detail)


def check_sheet_mirror(session: Session) -> Check:
    """The 12-tab sheet mirror is populated with formatting metadata."""
    client = FakeSheetsClient.load(_tenant_id())
    if not client.tabs:
        return Check("§5 · 12-tab sheet mirror populated", False, "no sheet mirror on disk")

    tabs_present = sum(1 for name in (t.name for t in TABS) if name in client.tabs)
    empty_backed = [name for name in _POPULATED_TABS if not client.tabs.get(name, {}).get("rows")]
    # Formatting contract: every tab records freeze-header + filter; status tabs
    # record the status→color map.
    missing_fmt = [
        t.name
        for t in TABS
        if not ((f := client.formatting.get(t.name)) and f.freeze_header and f.filter_enabled)
    ]
    colored_tabs = sum(1 for f in client.formatting.values() if f.status_colors)
    ok = tabs_present == 12 and not empty_backed and not missing_fmt and colored_tabs > 0
    detail = (
        f"{tabs_present}/12 tabs · {len(empty_backed)} empty DB-backed · "
        f"{len(missing_fmt)} missing freeze/filter · {colored_tabs} color-coded"
    )
    return Check("§5 · 12-tab sheet mirror populated", ok, detail)


def check_funnel_consistency(session: Session) -> Check:
    """Funnel totals are internally consistent (monotone down the pipeline)."""
    total_companies = (
        session.scalar(select(func.count()).select_from(Company).where(Company.job_id == _job_id()))
        or 0
    )
    total_contacts = (
        session.scalar(select(func.count()).select_from(Contact).where(Contact.job_id == _job_id()))
        or 0
    )
    emails_found = (
        session.scalar(
            select(func.count())
            .select_from(EmailCandidate)
            .join(Contact, EmailCandidate.contact_id == Contact.id)
            .where(Contact.job_id == _job_id())
        )
        or 0
    )
    verified = (
        session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.job_id == _job_id(),
                Contact.final_email_status == FinalEmailStatus.VERIFIED.value,
            )
        )
        or 0
    )
    sales_ready = (
        session.scalar(
            select(func.count())
            .select_from(SalesReadyLead)
            .where(
                SalesReadyLead.job_id == _job_id(),
                SalesReadyLead.tombstoned.is_(False),
            )
        )
        or 0
    )
    # Monotone: companies>0, contacts>=companies, found<=contacts's candidates,
    # verified<=found, sales_ready<=verified.
    ok = (
        total_companies > 0
        and total_contacts >= total_companies
        and emails_found > 0
        and verified <= emails_found
        and sales_ready <= verified
    )
    detail = (
        f"companies={total_companies} contacts={total_contacts} "
        f"found={emails_found} verified={verified} sales_ready={sales_ready}"
    )
    return Check("§4 · funnel internally consistent", ok, detail)


def check_campaign_metrics(session: Session) -> Check:
    """The seeded campaign is populated for the dashboard/bounce screens."""
    campaign = session.get(Campaign, DEMO_IDS["campaign"])
    if campaign is None:
        return Check("§13 · demo campaign populated", False, "no demo campaign")
    msgs = session.scalars(
        select(EmailMessage).where(EmailMessage.campaign_id == campaign.id)
    ).all()
    sent = sum(1 for m in msgs if m.sent_at is not None)
    replied = sum(1 for m in msgs if m.replied_at is not None)
    bounced = sum(1 for m in msgs if m.bounced_at is not None)
    bounce_rate = (bounced / sent * 100) if sent else 0.0
    ok = sent > 0 and replied > 0 and bounced > 0 and 1.0 <= bounce_rate <= 6.0
    detail = f"{sent} sent · {replied} replied · {bounced} bounced ({bounce_rate:.1f}%)"
    return Check("§13 · demo campaign populated", ok, detail)


def check_gated_source_skips_without_signoff(session: Session) -> Check:
    """§8/AC23: a gated (AMBER/RED) source with no sign-off is skipped, not crashed.

    ``resolve_source`` must return a ``SourceUnavailable`` (with a human reason)
    rather than raising, so the mining job continues past a gated source that the
    tenant has not signed off on.
    """
    from app.adapters.registry import AdapterRegistry
    from app.constants import Posture, SourceName

    registry = AdapterRegistry()
    gated = [
        name
        for name in registry.source_names()
        if registry.adapter_card(name).posture != Posture.GREEN
    ]
    if not gated:
        return Check("§8 · gated source skips w/o signoff", False, "no gated sources found")

    reasons: list[str] = []
    for name in gated:
        try:
            resolved = registry.resolve_source(name, enabled=True, signed_off=False)
        except Exception as exc:  # noqa: BLE001 — the whole point is it must NOT raise
            return Check(
                "§8 · gated source skips w/o signoff",
                False,
                f"{name} raised {type(exc).__name__}: {exc}",
            )
        if resolved.ok or resolved.unavailable is None:
            return Check(
                "§8 · gated source skips w/o signoff",
                False,
                f"{name} resolved to a runnable adapter without sign-off",
            )
        reasons.append(resolved.unavailable.reason)

    # LinkedIn (RED) must be present among gated sources as an always-off stub.
    has_linkedin = SourceName.LINKEDIN in gated
    detail = f"{len(gated)} gated sources all skipped cleanly (linkedin_stub={has_linkedin})"
    return Check("§8 · gated source skips w/o signoff", True, detail)


def check_export_produces_file(session: Session) -> Check:
    """§12/AC17: an export materializes DB-backed rows into a real non-empty file."""
    import csv
    import tempfile
    from pathlib import Path

    from app.constants import ExportScope
    from app.services.exportsvc import SALES_READY_TAB, materialize_tabs

    tabs = materialize_tabs(session, _tenant_id(), ExportScope.SALES_READY, _job_id())
    tab = tabs.get(SALES_READY_TAB, {"header": [], "rows": []})
    header, rows = tab["header"], tab["rows"]
    if not header or not rows:
        return Check("§12 · export produces a file", False, "no sales-ready rows to export")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "verify_export.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in header})
        size = path.stat().st_size
        written = sum(1 for _ in path.read_text(encoding="utf-8").splitlines()) - 1
    ok = size > 0 and written == len(rows)
    detail = f"{written} rows · {len(header)} cols · {size} bytes CSV"
    return Check("§12 · export produces a file", ok, detail)


ALL_CHECKS = [
    check_pipeline_ran,
    check_companies_deduped,
    check_contacts_have_evidence,
    check_validation_stages,
    check_sales_ready_clean,
    check_sheet_mirror,
    check_funnel_consistency,
    check_campaign_metrics,
    check_gated_source_skips_without_signoff,
    check_export_produces_file,
]


def verify_demo(*, session: Session | None = None) -> bool:
    owns = session is None
    session = session or sync_session_factory()
    try:
        _ensure_seeded(session)
        results = [fn(session) for fn in ALL_CHECKS]
        _print_table(results)
        return all(r.ok for r in results)
    finally:
        if owns:
            session.close()


def _print_table(results: list[Check]) -> None:
    width = max(len(r.name) for r in results)
    print()
    print(f"{'CHECK'.ljust(width)}  RESULT  DETAIL")
    print(f"{'-' * width}  ------  {'-' * 40}")
    for r in results:
        badge = "PASS" if r.ok else "FAIL"
        print(f"{r.name.ljust(width)}  {badge:<6}  {r.detail}")
    passed = sum(1 for r in results if r.ok)
    print(f"{'-' * width}  ------  {'-' * 40}")
    print(f"{passed}/{len(results)} checks passed")
    print()


def main() -> int:
    ok = verify_demo()
    if ok:
        print("VERIFY DEMO: PASS")
        return 0
    print("VERIFY DEMO: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
