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

import structlog
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

logger = structlog.get_logger(__name__)

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

        # --- done (mark complete first, then a single non-fatal sheet sync) ---
        _enter_stage(session, job, JobStage.SYNCING)
        _complete(session, job)
        summary["totals"] = recompute_and_persist_totals(session, job)
        session.commit()
        summary["sync"] = _safe_sync(session, job)
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


# Ordered pipeline steps: (finish_progress, work_fn). The driver runs each step
# whose finish_progress the job hasn't reached yet, commits after each, and is
# therefore resumable — a re-delivered task skips completed steps instead of
# re-running priced discovery/enrichment (fixes the double-discovery bug).
def _step_discovery(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    _enter_stage(session, job, JobStage.DISCOVERING)
    stages.run_discovery(session, redis_client, job)


def _step_extraction(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    _enter_stage(session, job, JobStage.EXTRACTING)
    for company in session.scalars(select(Company).where(Company.job_id == job.id)).all():
        stages.run_extraction(session, redis_client, job, company)


def _step_enrichment(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    _enter_stage(session, job, JobStage.ENRICHING)
    for contact in session.scalars(
        select(Contact).where(Contact.job_id == job.id, Contact.email.is_(None))
    ).all():
        stages.run_enrichment(session, redis_client, job, contact)


def _step_validation(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    _enter_stage(session, job, JobStage.VALIDATING)
    stages.validate_all_pending(session, redis_client, job)


def _step_sales_ready(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    _enter_stage(session, job, JobStage.SALES_READY)
    stages.recompute_sales_ready_for_job(session, job)


_STEPS: list[tuple[int, str]] = [
    (STAGE_PROGRESS[JobStage.DEDUPING], "_step_discovery"),
    (STAGE_PROGRESS[JobStage.EXTRACTING], "_step_extraction"),
    (STAGE_PROGRESS[JobStage.ENRICHING], "_step_enrichment"),
    (STAGE_PROGRESS[JobStage.VALIDATING], "_step_validation"),
    (STAGE_PROGRESS[JobStage.SALES_READY], "_step_sales_ready"),
]


def advance(job_id: uuid.UUID) -> None:
    """Run ``job_id`` to completion (broker path), committing after each stage.

    Called at job start and (legacy) by fan-out unit tasks. Resumable and
    pause/cancel-safe. On any stage exception the job is marked FAILED (with a
    failure event + best-effort sheet re-sync) and the exception is re-raised so
    Celery records the task failure; the mined data committed by earlier stages
    is preserved.
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
        try:
            _drive(session, redis_client, job)
        except JobCancelled:
            session.rollback()
            return
        except Exception as exc:
            session.rollback()
            _fail(session, job_id, exc)
            raise
    finally:
        session.close()


def _drive(session: Session, redis_client: redis.Redis, job: MiningJob) -> None:
    """Execute the pipeline steps in order, committing + checking pause/cancel
    between each, then finalize with a single (non-fatal) sheet sync."""
    if job.status != JobStatus.RUNNING:
        _begin_running(session, job)
        session.commit()

    for finish_pct, fn_name in _STEPS:
        if (job.progress_percent or 0) >= finish_pct:
            continue  # already done on a prior (re-delivered) run — resume
        session.refresh(job)
        if job.status in (JobStatus.PAUSED, JobStatus.CANCELLED):
            return
        if is_cancelled(redis_client, job.id):
            _cancel(session, job)
            session.commit()
            return
        globals()[fn_name](session, redis_client, job)
        job.progress_percent = max(job.progress_percent or 0, finish_pct)
        recompute_and_persist_totals(session, job)
        session.commit()

    # A pause/cancel that lands DURING the final stage (after that iteration's
    # pre-check) would otherwise be clobbered by the COMPLETED write below.
    # Re-check once more before finalizing so a late pause is honored.
    session.refresh(job)
    if job.status in (JobStatus.PAUSED, JobStatus.CANCELLED):
        return
    if is_cancelled(redis_client, job.id):
        _cancel(session, job)
        session.commit()
        return

    # --- finalize: mark complete + one durable sheet sync with final status/totals ---
    _enter_stage(session, job, JobStage.SYNCING)
    _complete(session, job)
    recompute_and_persist_totals(session, job)
    session.commit()  # COMPLETED + totals durable before touching the (flaky) sheet
    _safe_sync(session, job)
    session.commit()


def _safe_sync(session: Session, job: MiningJob) -> dict:
    """Flush to Google Sheets; a sheet error is logged and swallowed (the mined
    data is already committed, so one flaky external service never loses a run)."""
    try:
        return stages.run_sync(session, job.tenant_id)
    except Exception as exc:  # noqa: BLE001 - sync must never abort a completed job
        logger.warning(
            "sheet_sync_failed",
            job_id=str(job.id),
            error_type=exc.__class__.__name__,
            error=str(exc)[:300],
        )
        session.rollback()
        return {"synced": False, "error": exc.__class__.__name__}


def _fail(session: Session, job_id: uuid.UUID, exc: Exception) -> None:
    """Mark a job FAILED with a failure event + best-effort sheet re-sync."""
    job = session.get(MiningJob, job_id)
    if job is None:
        return
    job.status = JobStatus.FAILED
    job.completed_at = utcnow()
    publish_event(
        session,
        tenant_id=job.tenant_id,
        job_id=job.id,
        stage=JobStage.DONE,
        level="error",
        message=f"Job failed: {exc.__class__.__name__}: {str(exc)[:280]}",
    )
    recompute_and_persist_totals(session, job)
    session.commit()
    _safe_sync(session, job)  # surface 'failed' + partial totals in Mining_Jobs
    session.commit()


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
