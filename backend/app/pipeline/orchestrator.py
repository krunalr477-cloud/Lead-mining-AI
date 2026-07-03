"""Job orchestrator: the sync state machine over JobStage (spec §4).

Two entry points:

- ``advance(job_id)`` — the broker-driven driver. It opens its own session,
  checks the job's status at the stage boundary (pause/cancel-safe), runs the
  current stage's *fan-out* enqueue (or does the stage's work when it is
  non-fanned-out), and either transitions to the next stage or waits for the
  fan-out counter to reach 0 (the unit task that hits 0 calls advance() again).

- ``run_job_inline(job_id)`` — runs the WHOLE pipeline synchronously in-process
  with no broker. Used by tests, seeds, and verify-demo. It walks every stage in
  order, committing per stage, and returns a summary of row counts.

Progress + totals: after each stage the orchestrator updates
``MiningJob.progress_percent`` and ``MiningJob.totals_json`` and publishes a
JobEvent, so the live monitor and the Mining_Jobs sheet tab stay current.

Restart-safety: the fan-out counter is derived from the DB (the count of unit
work items), so a worker restart mid-stage can rebuild it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.constants import FinalEmailStatus, JobStage, JobStatus
from app.db import sync_session_factory, utcnow
from app.models import Company, Contact, EmailCandidate, MiningJob, SalesReadyLead
from app.pipeline import stages
from app.pipeline.runtime import is_cancelled
from app.services.events import publish_event
from app.workers.rate_limit import get_redis

if TYPE_CHECKING:
    import redis
    from sqlalchemy.orm import Session

__all__ = [
    "STAGE_ORDER",
    "STAGE_PROGRESS",
    "advance",
    "compute_totals",
    "recompute_and_persist_totals",
    "run_job_inline",
]

# Linear stage order (spec §4). RESOLVING_LOCATION and CRAWLING are folded into
# the discovery/extraction stages respectively for the mock pipeline, but every
# stage is still surfaced in events + progress for the monitor.
STAGE_ORDER: list[JobStage] = [
    JobStage.RESOLVING_LOCATION,
    JobStage.DISCOVERING,
    JobStage.DEDUPING,
    JobStage.CRAWLING,
    JobStage.EXTRACTING,
    JobStage.ENRICHING,
    JobStage.VALIDATING,
    JobStage.SYNCING,
    JobStage.SALES_READY,
    JobStage.DONE,
]

STAGE_PROGRESS: dict[JobStage, int] = {
    JobStage.RESOLVING_LOCATION: 5,
    JobStage.DISCOVERING: 20,
    JobStage.DEDUPING: 30,
    JobStage.CRAWLING: 45,
    JobStage.EXTRACTING: 60,
    JobStage.ENRICHING: 72,
    JobStage.VALIDATING: 85,
    JobStage.SYNCING: 93,
    JobStage.SALES_READY: 98,
    JobStage.DONE: 100,
}


class JobCancelled(Exception):
    """Raised internally when a paused/cancelled job should stop advancing."""


# --------------------------------------------------------------------------- #
# Totals
# --------------------------------------------------------------------------- #


def compute_totals(session: Session, job: MiningJob) -> dict:
    """Aggregate the funnel counters for a job (also drives the Mining_Jobs tab)."""
    total_companies = (
        session.scalar(select(func.count()).select_from(Company).where(Company.job_id == job.id))
        or 0
    )
    total_contacts = (
        session.scalar(select(func.count()).select_from(Contact).where(Contact.job_id == job.id))
        or 0
    )
    emails_found = (
        session.scalar(
            select(func.count())
            .select_from(EmailCandidate)
            .join(Contact, EmailCandidate.contact_id == Contact.id)
            .where(Contact.job_id == job.id)
        )
        or 0
    )

    status_counts: dict[str | None, int] = {
        row[0]: row[1]
        for row in session.execute(
            select(Contact.final_email_status, func.count())
            .where(Contact.job_id == job.id)
            .group_by(Contact.final_email_status)
        ).all()
    }
    verified = status_counts.get(FinalEmailStatus.VERIFIED.value, 0)
    review_states = {
        FinalEmailStatus.CATCH_ALL_REVIEW.value,
        FinalEmailStatus.RISK_REVIEW.value,
        FinalEmailStatus.LLM_LOW_CONFIDENCE.value,
        FinalEmailStatus.UNKNOWN_RETRY.value,
    }
    invalid_states = {
        FinalEmailStatus.INVALID_SYNTAX.value,
        FinalEmailStatus.DISPOSABLE_REJECTED.value,
        FinalEmailStatus.ROLE_BASED_REJECTED.value,
        FinalEmailStatus.MX_FAILED.value,
        FinalEmailStatus.PROVIDER_INVALID.value,
        FinalEmailStatus.SUPPRESSED.value,
    }
    review = sum(n for s, n in status_counts.items() if s in review_states)
    invalid = sum(n for s, n in status_counts.items() if s in invalid_states)

    sales_ready = (
        session.scalar(
            select(func.count())
            .select_from(SalesReadyLead)
            .where(SalesReadyLead.job_id == job.id, SalesReadyLead.tombstoned.is_(False))
        )
        or 0
    )

    return {
        "total_companies": int(total_companies),
        "total_contacts": int(total_contacts),
        "emails_found": int(emails_found),
        "verified_emails": int(verified),
        "invalid_emails": int(invalid),
        "review_emails": int(review),
        "sales_ready_count": int(sales_ready),
    }


def recompute_and_persist_totals(session: Session, job: MiningJob) -> dict:
    totals = compute_totals(session, job)
    merged = dict(job.totals_json or {})
    merged.update(totals)
    job.totals_json = merged
    session.flush()
    return merged


# --------------------------------------------------------------------------- #
# Inline whole-pipeline runner (no broker) — the verify/seed/test path
# --------------------------------------------------------------------------- #


def run_job_inline(job_id: uuid.UUID, *, session: Session | None = None) -> dict:
    """Run every stage synchronously for ``job_id`` and return a row-count summary.

    Commits after each stage. Safe to call from scripts/tests with no worker or
    broker running. Honors the cancel flag between stages.
    """
    owns_session = session is None
    session = session or sync_session_factory()
    redis_client = get_redis()
    try:
        job = session.get(MiningJob, job_id)
        if job is None:
            raise ValueError(f"MiningJob {job_id} not found")

        _begin_running(session, job)
        session.commit()

        summary: dict = {"skipped": False}

        # --- discovery + dedupe ---
        _enter_stage(session, job, JobStage.DISCOVERING)
        disc = stages.run_discovery(session, redis_client, job)
        summary["discovery"] = disc
        _finish_stage(session, job, JobStage.DEDUPING)
        session.commit()
        _guard_cancel(session, redis_client, job)

        # --- extraction (per company) ---
        _enter_stage(session, job, JobStage.EXTRACTING)
        companies = session.scalars(select(Company).where(Company.job_id == job.id)).all()
        ex_totals = {"contacts": 0, "emails": 0, "signals": 0}
        for company in companies:
            res = stages.run_extraction(session, redis_client, job, company)
            for k in ex_totals:
                ex_totals[k] += res[k]
        summary["extraction"] = ex_totals
        _finish_stage(session, job, JobStage.EXTRACTING)
        session.commit()
        _guard_cancel(session, redis_client, job)

        # --- enrichment (contacts missing email) ---
        _enter_stage(session, job, JobStage.ENRICHING)
        needy = session.scalars(
            select(Contact).where(Contact.job_id == job.id, Contact.email.is_(None))
        ).all()
        enriched = 0
        for contact in needy:
            enriched += stages.run_enrichment(session, redis_client, job, contact)["enriched"]
        summary["enrichment"] = {"enriched": enriched}
        _finish_stage(session, job, JobStage.ENRICHING)
        session.commit()
        _guard_cancel(session, redis_client, job)

        # --- validation (per email candidate) ---
        _enter_stage(session, job, JobStage.VALIDATING)
        val = stages.validate_all_pending(session, redis_client, job)
        summary["validation"] = val
        _finish_stage(session, job, JobStage.VALIDATING)
        session.commit()
        _guard_cancel(session, redis_client, job)

        # --- sales-ready ---
        _enter_stage(session, job, JobStage.SALES_READY)
        sr = stages.recompute_sales_ready_for_job(session, job)
        summary["sales_ready"] = sr
        session.commit()

        # --- sync to sheets ---
        _enter_stage(session, job, JobStage.SYNCING)
        sync = stages.run_sync(session, job.tenant_id)
        summary["sync"] = sync
        session.commit()

        # --- done ---
        _complete(session, job)
        summary["totals"] = recompute_and_persist_totals(session, job)
        # Re-flush the Mining_Jobs tab so the totals land in the sheet mirror.
        stages.run_sync(session, job.tenant_id)
        session.commit()
        return summary
    except JobCancelled:
        session.rollback()
        job = session.get(MiningJob, job_id)
        return {"skipped": True, "status": job.status if job else "unknown"}
    finally:
        if owns_session:
            session.close()


# --------------------------------------------------------------------------- #
# Broker-driven driver
# --------------------------------------------------------------------------- #


def advance(job_id: uuid.UUID) -> None:
    """Advance ``job_id`` from its current stage to the next (broker path).

    Called at job start and by the unit task that decrements a fan-out counter to
    zero. Idempotent and pause/cancel-safe: a paused/cancelled job stops here.

    In this phase the broker path delegates each stage to the same synchronous
    stage functions the inline runner uses (single-worker execution), then
    transitions. The fan-out counter machinery lives in the task modules; this
    driver is the transition authority.
    """
    session = sync_session_factory()
    redis_client = get_redis()
    try:
        job = session.get(MiningJob, job_id)
        if job is None:
            return
        if job.status in (
            JobStatus.PAUSED,
            JobStatus.CANCELLED,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
        ):
            return
        if is_cancelled(redis_client, job.id):
            _cancel(session, job)
            session.commit()
            return

        # Determine the stage to run from progress; default to discovery at start.
        current = _current_stage(job)
        _run_stage_and_transition(session, redis_client, job, current)
        session.commit()
    finally:
        session.close()


def _current_stage(job: MiningJob) -> JobStage:
    pct = job.progress_percent or 0
    for stage in STAGE_ORDER:
        if pct < STAGE_PROGRESS[stage]:
            return stage
    return JobStage.DONE


def _run_stage_and_transition(
    session: Session, redis_client: redis.Redis, job: MiningJob, stage: JobStage
) -> None:
    """Execute one stage synchronously, then recurse into the next until DONE.

    Single-worker broker execution mirrors the inline runner; a multi-worker
    fan-out lands in a later phase using the runtime counters.
    """
    if job.status != JobStatus.RUNNING:
        _begin_running(session, job)

    if stage in (JobStage.DISCOVERING, JobStage.RESOLVING_LOCATION):
        _enter_stage(session, job, JobStage.DISCOVERING)
        stages.run_discovery(session, redis_client, job)
        _finish_stage(session, job, JobStage.DEDUPING)
    elif stage in (JobStage.DEDUPING, JobStage.CRAWLING, JobStage.EXTRACTING):
        _enter_stage(session, job, JobStage.EXTRACTING)
        for company in session.scalars(select(Company).where(Company.job_id == job.id)).all():
            stages.run_extraction(session, redis_client, job, company)
        _finish_stage(session, job, JobStage.EXTRACTING)
    elif stage == JobStage.ENRICHING:
        _enter_stage(session, job, JobStage.ENRICHING)
        for contact in session.scalars(
            select(Contact).where(Contact.job_id == job.id, Contact.email.is_(None))
        ).all():
            stages.run_enrichment(session, redis_client, job, contact)
        _finish_stage(session, job, JobStage.ENRICHING)
    elif stage == JobStage.VALIDATING:
        _enter_stage(session, job, JobStage.VALIDATING)
        stages.validate_all_pending(session, redis_client, job)
        _finish_stage(session, job, JobStage.VALIDATING)
    elif stage == JobStage.SYNCING:
        _enter_stage(session, job, JobStage.SALES_READY)
        stages.recompute_sales_ready_for_job(session, job)
        _enter_stage(session, job, JobStage.SYNCING)
        stages.run_sync(session, job.tenant_id)
    elif stage in (JobStage.SALES_READY, JobStage.DONE):
        stages.recompute_sales_ready_for_job(session, job)
        stages.run_sync(session, job.tenant_id)
        _complete(session, job)
        recompute_and_persist_totals(session, job)
        stages.run_sync(session, job.tenant_id)
        return

    recompute_and_persist_totals(session, job)
    # Drive the remaining stages in this single-worker phase.
    if job.status == JobStatus.RUNNING and (job.progress_percent or 0) < 100:
        if is_cancelled(redis_client, job.id):
            _cancel(session, job)
            return
        _run_stage_and_transition(session, redis_client, job, _current_stage(job))


# --------------------------------------------------------------------------- #
# Stage bookkeeping helpers
# --------------------------------------------------------------------------- #


def _begin_running(session: Session, job: MiningJob) -> None:
    if job.started_at is None:
        job.started_at = utcnow()
    job.status = JobStatus.RUNNING
    publish_event(
        session,
        tenant_id=job.tenant_id,
        job_id=job.id,
        stage=JobStage.RESOLVING_LOCATION,
        message="Job started; resolving location and radius.",
    )
    job.progress_percent = max(
        job.progress_percent or 0, STAGE_PROGRESS[JobStage.RESOLVING_LOCATION]
    )
    session.flush()


def _enter_stage(session: Session, job: MiningJob, stage: JobStage) -> None:
    job.progress_percent = max(job.progress_percent or 0, STAGE_PROGRESS[stage] - 5)
    publish_event(
        session,
        tenant_id=job.tenant_id,
        job_id=job.id,
        stage=stage,
        message=f"Entering stage: {stage.value}.",
    )
    session.flush()


def _finish_stage(session: Session, job: MiningJob, stage: JobStage) -> None:
    job.progress_percent = max(job.progress_percent or 0, STAGE_PROGRESS[stage])
    recompute_and_persist_totals(session, job)
    session.flush()


def _complete(session: Session, job: MiningJob) -> None:
    job.status = JobStatus.COMPLETED
    job.progress_percent = 100
    job.completed_at = utcnow()
    publish_event(
        session,
        tenant_id=job.tenant_id,
        job_id=job.id,
        stage=JobStage.DONE,
        level="success",
        message="Job complete.",
    )
    session.flush()


def _cancel(session: Session, job: MiningJob) -> None:
    job.status = JobStatus.CANCELLED
    job.completed_at = utcnow()
    publish_event(
        session,
        tenant_id=job.tenant_id,
        job_id=job.id,
        stage=JobStage.DONE,
        level="warning",
        message="Job cancelled.",
    )
    session.flush()


def _guard_cancel(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    session.refresh(job)
    if is_cancelled(redis_client, job.id) or job.status in (
        JobStatus.CANCELLED,
        JobStatus.PAUSED,
    ):
        if job.status != JobStatus.PAUSED:
            _cancel(session, job)
            session.commit()
        raise JobCancelled
