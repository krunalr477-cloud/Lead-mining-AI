"""Purge fabricated mock-directories companies from a REAL tenant.

Before Batch 6.1, the registry silently served MockDirectoriesAdapter in real
jobs (DIRECTORIES had no live adapter), injecting demo-corpus companies into a
real tenant's DB + Google Sheet. This script removes them:

- Companies whose ONLY CompanySource evidence is ``directories`` are deleted
  (with their contacts / email candidates / validation checks via cascade, and
  their SalesReadyLead rows explicitly — those FKs are SET NULL, not CASCADE).
- Companies that MERGED directories evidence with a real source survive, but
  lose the directories CompanySource row and any ``*-clone.example`` mock URLs
  from ``source_urls``.
- Affected jobs get totals + sales-ready recomputed and a warning JobEvent;
  the sheet re-syncs so removed rows disappear (the engine reconciles deletes).

Dry-run by default. Usage:

    uv run python -m scripts.cleanup_mock_directories --tenant-id <uuid>
    uv run python -m scripts.cleanup_mock_directories --tenant-id <uuid> --apply
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.constants import JobStage
from app.db import sync_session_factory
from app.models import Company, CompanySource, Contact, MiningJob, SalesReadyLead
from app.pipeline import stages
from app.pipeline.orchestrator import recompute_and_persist_totals
from app.services.events import publish_event

_MOCK_URL_MARKER = "-clone.example"


def cleanup_directories_companies(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    job_id: uuid.UUID | None = None,
    apply: bool = False,
    sheet_sync: bool = True,
) -> dict:
    """Find (and with ``apply=True`` remove) mock-directories pollution.

    Returns a summary dict of what was (or would be) removed.
    """
    dir_companies = select(CompanySource.company_id).where(
        CompanySource.source_name == "directories"
    )
    other_companies = select(CompanySource.company_id).where(
        CompanySource.source_name != "directories"
    )

    doomed_q = select(Company).where(
        Company.tenant_id == tenant_id,
        Company.id.in_(dir_companies),
        ~Company.id.in_(other_companies),
    )
    survivor_q = select(Company).where(
        Company.tenant_id == tenant_id,
        Company.id.in_(dir_companies),
        Company.id.in_(other_companies),
    )
    if job_id is not None:
        doomed_q = doomed_q.where(Company.job_id == job_id)
        survivor_q = survivor_q.where(Company.job_id == job_id)

    doomed = session.scalars(doomed_q).all()
    survivors = session.scalars(survivor_q).all()
    doomed_ids = [c.id for c in doomed]

    contacts_riding = (
        session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.company_id.in_(doomed_ids))
        )
        if doomed_ids
        else 0
    )
    leads_riding = (
        session.scalar(
            select(func.count())
            .select_from(SalesReadyLead)
            .where(SalesReadyLead.company_id.in_(doomed_ids))
        )
        if doomed_ids
        else 0
    )
    affected_jobs = sorted(
        {c.job_id for c in [*doomed, *survivors] if c.job_id is not None},
        key=str,
    )

    summary = {
        "tenant_id": str(tenant_id),
        "companies_to_delete": len(doomed),
        "contacts_riding": int(contacts_riding or 0),
        "sales_ready_leads_riding": int(leads_riding or 0),
        "merged_survivors_to_strip": len(survivors),
        "affected_jobs": [str(j) for j in affected_jobs],
        "applied": bool(apply),
    }
    if not apply:
        return summary

    # SalesReadyLead FKs are SET NULL — delete them explicitly or they'd linger
    # as orphaned leads pointing at nothing.
    if doomed_ids:
        session.execute(
            delete(SalesReadyLead).where(SalesReadyLead.company_id.in_(doomed_ids))
        )
    for company in doomed:
        session.delete(company)  # ORM cascade removes contacts/candidates/checks

    for company in survivors:
        session.execute(
            delete(CompanySource).where(
                CompanySource.company_id == company.id,
                CompanySource.source_name == "directories",
            )
        )
        if company.source_urls:
            company.source_urls = [
                u for u in company.source_urls if _MOCK_URL_MARKER not in (u or "")
            ]
    session.flush()

    for jid in affected_jobs:
        job = session.get(MiningJob, jid)
        if job is None:
            continue
        recompute_and_persist_totals(session, job)
        stages.recompute_sales_ready_for_job(session, job)
        publish_event(
            session,
            tenant_id=tenant_id,
            job_id=job.id,
            stage=JobStage.DONE,
            level="warning",
            message=(
                f"Removed {summary['companies_to_delete']} fabricated demo companies "
                "(mock directories data injected before the registry fix)."
            ),
        )
    session.commit()

    if sheet_sync:
        # The sheet engine reconciles deletions (rows whose keys vanished from
        # the DB are removed from the tabs).
        try:
            summary["sheet_sync"] = stages.run_sync(session, tenant_id)
            session.commit()
        except Exception as exc:  # noqa: BLE001 - sheet errors must not undo the purge
            session.rollback()
            summary["sheet_sync"] = {"error": f"{exc.__class__.__name__}: {exc}"}

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    parser.add_argument("--job-id", type=uuid.UUID, default=None)
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    parser.add_argument("--skip-sheet-sync", action="store_true")
    args = parser.parse_args()

    session = sync_session_factory()
    try:
        summary = cleanup_directories_companies(
            session,
            args.tenant_id,
            job_id=args.job_id,
            apply=args.apply,
            sheet_sync=not args.skip_sheet_sync,
        )
    finally:
        session.close()

    mode = "APPLIED" if args.apply else "DRY-RUN (pass --apply to execute)"
    print(f"[cleanup_mock_directories] {mode}")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
