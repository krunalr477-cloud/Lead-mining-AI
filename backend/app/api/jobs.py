"""Mining-job endpoints (spec §7 / §19).

POST   /jobs                create a draft job (all §7 inputs)
GET    /jobs                list + search (name/type/location/source/status/date/creator/text)
GET    /jobs/{id}           one job
POST   /jobs/{id}/start     enqueue discovery (or run inline with ?inline=true for demo)
POST   /jobs/{id}/pause     pause a running job
POST   /jobs/{id}/cancel    cancel a job (sets the Redis cancel flag)
GET    /jobs/{id}/results   companies + contacts + funnel counts
POST   /jobs/estimate       preview: est. companies/cost/runtime + compliance warnings
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from starlette.concurrency import run_in_threadpool

from app.adapters.registry import get_registry
from app.adapters.sources.google_maps import MAX_PAGES as _PLACES_MAX_PAGES
from app.adapters.sources.google_maps import SEARCH_TEXT_UNIT_COST as _PLACES_UNIT_COST
from app.config import get_settings
from app.constants import JobStage, JobStatus, Posture, SourceName, SourceRunStatus
from app.db import utcnow
from app.deps import CurrentUser, SessionDep, TenantId, require
from app.models import Company, Contact, DataSourceConfig, MiningJob, SourceRun, Tenant
from app.schemas.company import CompanyOut
from app.schemas.contact import ContactOut
from app.schemas.job import (
    ComplianceWarning,
    JobCreate,
    JobEstimate,
    JobListItem,
    JobOut,
    JobStartRequest,
    SourceRunSummary,
)
from app.services.events import apublish_event

router = APIRouter(prefix="/jobs", tags=["jobs"])

ReadActor = Annotated[MiningJob, Depends(require("jobs:read"))]
CreateActor = Annotated[MiningJob, Depends(require("jobs:create"))]
ControlActor = Annotated[MiningJob, Depends(require("jobs:control"))]


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


# Places (New) returns 20 results/page; discovery stops at MAX_PAGES pages, so a
# single Google Maps search can surface at most this many businesses.
PLACES_DISCOVERY_CEILING = _PLACES_MAX_PAGES * 20


_VALID_SOURCES = frozenset(s.value for s in SourceName)


def _validate_sources(selected: list[str]) -> None:
    """Reject source slugs the pipeline doesn't recognize, so a frontend/backend
    naming drift fails loudly at request time instead of silently dropping the
    source mid-run (e.g. the historical public_directories/google_jobs mismatch)."""
    unknown = [s for s in selected if s not in _VALID_SOURCES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown data source(s): {', '.join(sorted(unknown))}. "
                f"Valid sources: {', '.join(sorted(_VALID_SOURCES))}."
            ),
        )


async def _get_job(session: SessionDep, tenant_id: uuid.UUID, job_id: uuid.UUID) -> MiningJob:
    job = await session.get(MiningJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate,
    _actor: CreateActor,
    user: CurrentUser,
    tenant_id: TenantId,
    session: SessionDep,
) -> MiningJob:
    selected = body.selected_sources or [
        SourceName.GOOGLE_MAPS.value,
        SourceName.COMPANY_WEBSITES.value,
        SourceName.DIRECTORIES.value,
    ]
    _validate_sources(selected)
    notes = body.notes
    # Persist enrichment/validation/output options into notes-adjacent totals_json
    # metadata so nothing is lost (dedicated columns land in later phases).
    metadata = {
        "enrichment_providers": body.enrichment_providers,
        "validation_stages": body.validation_stages,
        "output_options": body.output_options,
        "deep_discovery": bool(body.deep_discovery),
    }
    job = MiningJob(
        tenant_id=tenant_id,
        created_by=user.id,
        name=body.name,
        company_type=body.company_type,
        services=body.services,
        country=body.country,
        state=body.state,
        city=body.city,
        zipcode=body.zipcode,
        latitude=_dec(body.latitude),
        longitude=_dec(body.longitude),
        radius_km=_dec(body.radius_km),
        company_size_min=body.company_size_min,
        company_size_max=body.company_size_max,
        contact_roles=body.contact_roles,
        exclude_keywords=body.exclude_keywords,
        selected_sources=selected,
        status=JobStatus.DRAFT,
        totals_json={"job_options": metadata},
        notes=notes,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("", response_model=list[JobListItem])
async def list_jobs(
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    q: Annotated[str | None, Query(description="Free-text over name/city/type")] = None,
    name: str | None = None,
    company_type: str | None = None,
    location: str | None = None,
    source: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    created_by: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MiningJob]:
    stmt = select(MiningJob).where(MiningJob.tenant_id == tenant_id)
    if name:
        stmt = stmt.where(MiningJob.name.ilike(f"%{name}%"))
    if company_type:
        stmt = stmt.where(MiningJob.company_type.ilike(f"%{company_type}%"))
    if location:
        like = f"%{location}%"
        stmt = stmt.where(
            or_(
                MiningJob.city.ilike(like),
                MiningJob.state.ilike(like),
                MiningJob.country.ilike(like),
                MiningJob.zipcode.ilike(like),
            )
        )
    if source:
        stmt = stmt.where(MiningJob.selected_sources.contains([source]))
    if status_filter:
        stmt = stmt.where(MiningJob.status == status_filter)
    if created_by:
        stmt = stmt.where(MiningJob.created_by == created_by)
    if date_from:
        stmt = stmt.where(MiningJob.created_at >= date_from)
    if date_to:
        stmt = stmt.where(MiningJob.created_at <= date_to)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                MiningJob.name.ilike(like),
                MiningJob.city.ilike(like),
                MiningJob.company_type.ilike(like),
            )
        )
    stmt = stmt.order_by(MiningJob.created_at.desc()).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID, _actor: ReadActor, tenant_id: TenantId, session: SessionDep
) -> MiningJob:
    return await _get_job(session, tenant_id, job_id)


@router.post("/{job_id}/start", response_model=JobOut)
async def start_job(
    job_id: uuid.UUID,
    _actor: ControlActor,
    tenant_id: TenantId,
    session: SessionDep,
    body: JobStartRequest | None = None,
    inline: Annotated[
        bool, Query(description="Run the whole pipeline synchronously (demo)")
    ] = False,
) -> MiningJob:
    job = await _get_job(session, tenant_id, job_id)
    if job.status in (JobStatus.RUNNING, JobStatus.COMPLETED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Job already {job.status}"
        )
    # Clear any stale cancel flag from a previous run.
    from app.pipeline.runtime import cancel_key
    from app.services.events import get_async_redis

    await get_async_redis().delete(cancel_key(job.id))

    job.status = JobStatus.QUEUED
    await apublish_event(
        session,
        tenant_id=tenant_id,
        job_id=job.id,
        stage=JobStage.RESOLVING_LOCATION,
        message="Job queued.",
    )
    await session.commit()

    run_inline = inline or (body.inline if body else False)
    if run_inline:
        from app.pipeline.orchestrator import run_job_inline

        await run_in_threadpool(run_job_inline, job.id)
    else:
        # Enqueue the discovery task; the orchestrator drives the rest.
        from app.workers.tasks.google_maps import discover_places

        discover_places.delay(str(job.id))

    await session.refresh(job)
    return job


@router.post("/{job_id}/pause", response_model=JobOut)
async def pause_job(
    job_id: uuid.UUID, _actor: ControlActor, tenant_id: TenantId, session: SessionDep
) -> MiningJob:
    job = await _get_job(session, tenant_id, job_id)
    if job.status not in (JobStatus.RUNNING, JobStatus.QUEUED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Cannot pause a {job.status} job"
        )
    job.status = JobStatus.PAUSED
    await apublish_event(
        session,
        tenant_id=tenant_id,
        job_id=job.id,
        stage=JobStage.DONE,
        level="warning",
        message="Job paused.",
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: uuid.UUID, _actor: ControlActor, tenant_id: TenantId, session: SessionDep
) -> MiningJob:
    job = await _get_job(session, tenant_id, job_id)
    if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Job already {job.status}"
        )
    from app.pipeline.runtime import cancel_key
    from app.services.events import get_async_redis

    await get_async_redis().set(cancel_key(job.id), "1")
    job.status = JobStatus.CANCELLED
    job.completed_at = utcnow()
    await apublish_event(
        session,
        tenant_id=tenant_id,
        job_id=job.id,
        stage=JobStage.DONE,
        level="warning",
        message="Job cancelled.",
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/{job_id}/results")
async def job_results(
    job_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    job = await _get_job(session, tenant_id, job_id)
    companies = list(
        await session.scalars(
            select(Company)
            .where(Company.job_id == job.id)
            .order_by(Company.created_at)
            .limit(limit)
            .offset(offset)
        )
    )
    contacts = list(
        await session.scalars(
            select(Contact)
            .where(Contact.job_id == job.id)
            .order_by(Contact.created_at)
            .limit(limit)
            .offset(offset)
        )
    )
    return {
        "job_id": str(job.id),
        "status": job.status,
        "totals": job.totals_json or {},
        "companies": [CompanyOut.model_validate(c).model_dump() for c in companies],
        "contacts": [ContactOut.model_validate(c).model_dump() for c in contacts],
    }


@router.get("/{job_id}/sources", response_model=list[SourceRunSummary])
async def job_sources(
    job_id: uuid.UUID,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> list[SourceRunSummary]:
    """Aggregated per-source activity for the Pipeline Activity panel — real
    work counters from source_runs (one row per source, not per run; a single
    job can log hundreds of per-company extract runs)."""
    job = await _get_job(session, tenant_id, job_id)
    rows = (
        await session.execute(
            select(
                SourceRun.source_name,
                func.count().label("runs"),
                func.count().filter(SourceRun.status == SourceRunStatus.COMPLETED),
                func.count().filter(SourceRun.status == SourceRunStatus.FAILED),
                func.count().filter(SourceRun.status == SourceRunStatus.SKIPPED),
                func.count().filter(
                    SourceRun.status.in_(
                        (SourceRunStatus.PENDING.value, SourceRunStatus.RUNNING.value)
                    )
                ),
                func.coalesce(func.sum(SourceRun.records_found), 0),
                func.coalesce(func.sum(SourceRun.records_imported), 0),
                func.coalesce(func.sum(SourceRun.retry_count), 0),
                func.min(SourceRun.started_at),
                func.max(SourceRun.completed_at),
            )
            .where(SourceRun.job_id == job.id)
            .group_by(SourceRun.source_name)
            .order_by(SourceRun.source_name)
        )
    ).all()
    # Most recent error per source (DISTINCT ON — Postgres).
    error_rows = (
        await session.execute(
            select(SourceRun.source_name, SourceRun.error_message)
            .where(SourceRun.job_id == job.id, SourceRun.error_message.is_not(None))
            .order_by(SourceRun.source_name, SourceRun.created_at.desc())
            .distinct(SourceRun.source_name)
        )
    ).all()
    last_errors = dict(error_rows)
    return [
        SourceRunSummary(
            source_name=r[0],
            runs=r[1],
            completed=r[2],
            failed=r[3],
            skipped=r[4],
            in_progress=r[5],
            records_found=int(r[6]),
            records_imported=int(r[7]),
            retries=int(r[8]),
            last_error=last_errors.get(r[0]),
            first_started_at=r[9],
            last_completed_at=r[10],
        )
        for r in rows
    ]


@router.post("/estimate", response_model=JobEstimate)
async def estimate_job(
    body: JobCreate,
    _actor: ReadActor,
    tenant_id: TenantId,
    session: SessionDep,
) -> JobEstimate:
    selected = body.selected_sources or [
        SourceName.GOOGLE_MAPS.value,
        SourceName.COMPANY_WEBSITES.value,
        SourceName.DIRECTORIES.value,
    ]
    _validate_sources(selected)
    registry = get_registry()
    configs = {
        c.source_name: c
        for c in await session.scalars(
            select(DataSourceConfig).where(DataSourceConfig.tenant_id == tenant_id)
        )
    }

    # Rough company estimate from the discovery sources selected. Google Maps is
    # bounded by the Places (New) pagination cap (MAX_PAGES x 20 results/page) per
    # query; variant fan-out (diminishing returns) and deep-discovery tiling
    # raise the ceiling.
    settings = get_settings()
    variants = max(1, min(settings.places_query_variants, 6))
    maps_estimate = int(PLACES_DISCOVERY_CEILING * (1 + 0.35 * (variants - 1)))
    tiles = 7 if body.deep_discovery else 1
    if body.deep_discovery:
        maps_estimate = int(maps_estimate * 2.5)  # tiles overlap heavily; not 7x
    per_source = {
        SourceName.GOOGLE_MAPS.value: maps_estimate,
        SourceName.DIRECTORIES.value: 160,
        SourceName.YELLOW_PAGES.value: 12,
        SourceName.CLUTCH.value: 8,
        SourceName.INDEED.value: 10,
        SourceName.LINKEDIN.value: 6,
    }
    warnings: list[ComplianceWarning] = []
    est_companies = 0
    contributing: set[str] = set()  # sources that will actually run and yield rows
    for src in selected:
        try:
            name = SourceName(src)
        except ValueError:
            continue
        card = registry.adapter_card(name)
        cfg = configs.get(name.value)
        resolved = registry.resolve_source(
            name,
            enabled=bool(cfg.enabled) if cfg else False,
            signed_off=bool(cfg and cfg.signoff_at is not None),
        )
        # A source that won't run contributes 0 companies — the estimate must not
        # promise yield from a source the pipeline is going to skip (directories
        # previously added a fictional 160 while having no live adapter).
        if resolved.ok and name.value in per_source:
            est_companies += per_source[name.value]
            contributing.add(name.value)
        if not resolved.ok and card.posture == Posture.GREEN:
            reason = resolved.unavailable.reason if resolved.unavailable else "unavailable"
            warnings.append(
                ComplianceWarning(
                    source=name.value,
                    posture="warning",
                    message=f"{name.value} will be skipped in this run: {reason}.",
                )
            )
        if name == SourceName.GOOGLE_MAPS:
            deep_note = (
                f" Deep discovery is ON: up to {tiles} area tiles x {variants} query "
                "variants are searched (higher cost, wider coverage)."
                if body.deep_discovery
                else " Enable Deep discovery to sweep the area in 7 tiles for wider coverage."
            )
            warnings.append(
                ComplianceWarning(
                    source=name.value,
                    posture="info",
                    message=(
                        f"Google Maps returns at most ~{PLACES_DISCOVERY_CEILING} "
                        f"businesses per search (Places API pagination limit); this job "
                        f"fans out {variants} query variant(s)." + deep_note
                    ),
                )
            )
        if card.posture != Posture.GREEN:
            reason = (
                resolved.unavailable.reason
                if resolved.unavailable
                else "requires compliance sign-off"
            )
            warnings.append(
                ComplianceWarning(
                    source=name.value,
                    posture=card.posture.value,
                    message=f"{name.value} is {card.posture.value.upper()}: {reason}. {card.legal_note}",
                )
            )

    # ~40% dedupe overlap when both maps + directories actually contribute.
    if (
        SourceName.GOOGLE_MAPS.value in contributing
        and SourceName.DIRECTORIES.value in contributing
    ):
        est_companies = int(est_companies * 0.78)
    est_low = int(est_companies * 0.85)
    est_high = int(est_companies * 1.1)

    # Cost: explicit Places search math + ~2.5 contacts/company for the
    # downstream provider costs (enrichment + verify + LLM per email).
    est_contacts = int(est_companies * 2.5)
    places_searches = min(variants * tiles, settings.places_max_searches_per_job)
    places_cost = (
        (places_searches * _PLACES_MAX_PAGES * _PLACES_UNIT_COST + 0.005)  # + one geocode
        if SourceName.GOOGLE_MAPS.value in contributing
        else 0.0
    )
    cost = (
        places_cost
        + est_contacts * 0.10 * 0.18  # enrichment for ~18% missing
        + est_contacts * 0.0008  # verifier
        + est_contacts * 0.0002  # llm
    )
    runtime = max(20, int(est_companies * 0.4))

    tenant = await session.get(Tenant, tenant_id)
    sheet_target = (
        tenant.google_spreadsheet_id
        if tenant and tenant.google_spreadsheet_id
        else f"fake-sheet-{tenant_id}"
    )

    return JobEstimate(
        estimated_companies_min=est_low,
        estimated_companies_max=est_high,
        estimated_cost_usd=round(cost, 2),
        estimated_runtime_seconds=runtime,
        compliance_warnings=warnings,
        sheet_target=sheet_target,
        selected_sources=selected,
    )
