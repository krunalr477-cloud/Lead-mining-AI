"""End-to-end pipeline integration tests against live Postgres + Redis.

These run the real mock pipeline (registry → mock adapters → validation decision
machine → dedupe → sales-ready → sheet mirror) via ``run_job_inline`` on a SMALL
job, asserting the same invariants ``verify_demo`` checks but in miniature so they
stay fast enough for CI. A separate test exercises the cancel-flag path.

Marker: ``integration`` (needs postgres+redis; excluded from the pure unit run).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    AccessMethod,
    FinalEmailStatus,
    JobStatus,
    Posture,
    Role,
    SourceName,
    StageStatus,
)
from app.db import sync_session_factory
from app.models import (
    Company,
    Contact,
    DataSourceConfig,
    EmailCandidate,
    MiningJob,
    SalesReadyLead,
    Tenant,
    User,
    ValidationCheck,
    ValidationRuleSet,
)
from app.models.settings_models import default_validation_rules
from app.pipeline.orchestrator import compute_totals, run_job_inline
from app.pipeline.runtime import mark_cancelled
from app.workers.rate_limit import get_redis

pytestmark = pytest.mark.integration

# Keep the fixture small: the maps corpus emits MAPS_DEMO_LIMIT companies, but a
# 12-company slice is enough to exercise every stage and stays CI-fast. We cap by
# monkeypatching the emit limit for the test job only.
SMALL_COMPANY_TARGET = 12


@pytest.fixture()
def session() -> Iterator[Session]:
    s = sync_session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _make_tenant(session: Session) -> tuple[Tenant, User]:
    tenant = Tenant(name=f"E2E {uuid.uuid4().hex[:8]}")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.id,
        name="E2E Admin",
        email=f"e2e-{tenant.id}@leadmine.local",
        role=Role.ADMIN,
    )
    session.add(user)
    session.add(ValidationRuleSet(tenant_id=tenant.id, rules=default_validation_rules()))
    for sn in (SourceName.GOOGLE_MAPS, SourceName.COMPANY_WEBSITES, SourceName.DIRECTORIES):
        session.add(
            DataSourceConfig(
                tenant_id=tenant.id,
                source_name=sn.value,
                enabled=True,
                compliance_posture=Posture.GREEN.value,
                access_method=AccessMethod.MOCK.value,
                requires_signoff=False,
            )
        )
    session.flush()
    return tenant, user


def _make_job(session: Session, tenant: Tenant, user: User) -> MiningJob:
    job = MiningJob(
        tenant_id=tenant.id,
        created_by=user.id,
        name="E2E small run",
        company_type="CA Firm",
        services=["Audit", "Tax Filing"],
        country="India",
        state="Gujarat",
        city="Ahmedabad",
        latitude=23.0225,
        longitude=72.5714,
        radius_km=20,
        company_size_min=50,
        company_size_max=200,
        contact_roles=["Founder", "CEO", "Managing Partner", "Director", "Partner"],
        exclude_keywords=["HR", "Careers", "Jobs", "Intern", "Support"],
        selected_sources=[
            SourceName.GOOGLE_MAPS.value,
            SourceName.COMPANY_WEBSITES.value,
            SourceName.DIRECTORIES.value,
        ],
        status=JobStatus.QUEUED,
    )
    session.add(job)
    session.flush()
    return job


@pytest.fixture()
def small_pipeline(session: Session, monkeypatch: pytest.MonkeyPatch):
    """Run a 12-company pipeline to completion; yield (session, job)."""
    # Shrink discovery to a small, deterministic slice for CI speed.
    monkeypatch.setattr("app.adapters.mock.google_maps.MAPS_DEMO_LIMIT", SMALL_COMPANY_TARGET)
    monkeypatch.setattr(
        "app.adapters.mock.directories.MockDirectoriesAdapter.discover",
        _no_directory_discover,
    )
    tenant, user = _make_tenant(session)
    job = _make_job(session, tenant, user)
    session.commit()
    try:
        run_job_inline(job.id, session=session)
        session.commit()
        yield session, job
    finally:
        session.rollback()
        session.delete(session.get(Tenant, tenant.id))
        session.commit()


async def _no_directory_discover(self, job, ctx):  # noqa: ANN001, D401
    """Directories yield nothing in the small e2e run (keeps the count tight)."""
    return
    yield  # pragma: no cover - makes this an async generator


# --------------------------------------------------------------------------- #
# End-to-end invariants (miniature verify_demo)
# --------------------------------------------------------------------------- #


def test_pipeline_completes_and_produces_rows(small_pipeline):
    session, job = small_pipeline
    session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.progress_percent == 100

    companies = session.scalar(
        select(func.count()).select_from(Company).where(Company.job_id == job.id)
    )
    contacts = session.scalar(
        select(func.count()).select_from(Contact).where(Contact.job_id == job.id)
    )
    assert companies == SMALL_COMPANY_TARGET
    assert contacts >= companies  # at least one contact per company


def test_companies_are_deduplicated(small_pipeline):
    session, job = small_pipeline
    dup_keys = session.execute(
        select(Company.dedupe_key, func.count())
        .where(Company.tenant_id == job.tenant_id, Company.dedupe_key.is_not(None))
        .group_by(Company.dedupe_key)
        .having(func.count() > 1)
    ).all()
    assert dup_keys == []


def test_contacts_have_roles_and_source_evidence(small_pipeline):
    session, job = small_pipeline
    contacts = session.scalars(select(Contact).where(Contact.job_id == job.id)).all()
    assert contacts
    for c in contacts:
        assert c.role_category is not None
        assert c.source_type is not None
        assert c.source_page is not None


def test_every_validation_stage_ran(small_pipeline):
    session, job = small_pipeline
    checks = session.scalars(
        select(ValidationCheck)
        .join(Contact, ValidationCheck.contact_id == Contact.id)
        .where(Contact.job_id == job.id)
    ).all()
    assert checks
    valid = {s.value for s in StageStatus}
    for c in checks:
        for col in (c.syntax_status, c.disposable_status, c.role_based_status, c.mx_status):
            assert col in valid
            assert col != StageStatus.PENDING.value
        assert c.final_status is not None


def test_sales_ready_only_verified_non_suppressed(small_pipeline):
    session, job = small_pipeline
    leads = session.scalars(
        select(SalesReadyLead).where(
            SalesReadyLead.job_id == job.id,
            SalesReadyLead.tombstoned.is_(False),
        )
    ).all()
    for lead in leads:
        assert lead.validation_status == FinalEmailStatus.VERIFIED.value
        assert lead.email


def test_funnel_is_internally_consistent(small_pipeline):
    session, job = small_pipeline
    totals = compute_totals(session, job)
    found = session.scalar(
        select(func.count())
        .select_from(EmailCandidate)
        .join(Contact, EmailCandidate.contact_id == Contact.id)
        .where(Contact.job_id == job.id)
    )
    assert totals["total_companies"] > 0
    assert totals["total_contacts"] >= totals["total_companies"]
    assert totals["verified_emails"] <= found
    assert totals["sales_ready_count"] <= totals["verified_emails"]


def test_pipeline_is_deterministic(session: Session, monkeypatch: pytest.MonkeyPatch):
    """The SAME job (same fixed job_id) produces the same funnel when re-run.

    Determinism is keyed on job_id (discovery order) + stable company identity
    (extraction/validation), so clearing the produced rows and re-running the
    exact same job must reproduce the funnel byte-for-byte. This is the property
    the fixed-UUID demo seed relies on.
    """
    monkeypatch.setattr("app.adapters.mock.google_maps.MAPS_DEMO_LIMIT", SMALL_COMPANY_TARGET)
    monkeypatch.setattr(
        "app.adapters.mock.directories.MockDirectoriesAdapter.discover",
        _no_directory_discover,
    )
    tenant, user = _make_tenant(session)
    job = _make_job(session, tenant, user)
    session.commit()
    try:
        run_job_inline(job.id, session=session)
        session.commit()
        first = compute_totals(session, job)

        # Wipe the produced rows (companies cascade to contacts/emails/checks/
        # sales-ready) and reset the job, then re-run the identical job_id.
        session.query(SalesReadyLead).filter(SalesReadyLead.job_id == job.id).delete()
        session.query(Company).filter(Company.job_id == job.id).delete()
        job.status = JobStatus.QUEUED
        job.progress_percent = 0
        job.totals_json = {}
        session.commit()

        run_job_inline(job.id, session=session)
        session.commit()
        second = compute_totals(session, job)

        assert first == second
    finally:
        session.rollback()
        session.delete(session.get(Tenant, tenant.id))
        session.commit()


# --------------------------------------------------------------------------- #
# Cancel path
# --------------------------------------------------------------------------- #


def test_cancel_flag_halts_pipeline(session: Session, monkeypatch: pytest.MonkeyPatch):
    """Setting the Redis cancel flag stops an inline run and marks it CANCELLED."""
    monkeypatch.setattr("app.adapters.mock.google_maps.MAPS_DEMO_LIMIT", SMALL_COMPANY_TARGET)
    tenant, user = _make_tenant(session)
    job = _make_job(session, tenant, user)
    session.commit()

    redis_client = get_redis()
    mark_cancelled(redis_client, job.id)
    try:
        result = run_job_inline(job.id, session=session)
        session.commit()

        # The run stops at a stage boundary and reports it was skipped.
        assert result.get("skipped") is True
        session.refresh(job)
        assert job.status == JobStatus.CANCELLED
        assert job.progress_percent < 100

        # No sales-ready leads should have been materialized for a cancelled job.
        sales_ready = session.scalar(
            select(func.count()).select_from(SalesReadyLead).where(SalesReadyLead.job_id == job.id)
        )
        assert sales_ready == 0
    finally:
        redis_client.delete(f"job:{job.id}:cancelled")
        session.rollback()
        session.delete(session.get(Tenant, tenant.id))
        session.commit()


# --------------------------------------------------------------------------- #
# Reliability: FAILED-marking + non-fatal sheet sync (broker `advance` path)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def force_demo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force mock adapters regardless of the ambient .env DEMO_MODE."""
    from app.config import get_settings

    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_stage_failure_marks_job_failed(
    session: Session, monkeypatch: pytest.MonkeyPatch, force_demo: None
):
    """A stage exception on the broker path marks the job FAILED and PRESERVES the
    data committed by earlier stages (per-stage commit + _fail)."""
    monkeypatch.setattr("app.adapters.mock.google_maps.MAPS_DEMO_LIMIT", SMALL_COMPANY_TARGET)
    monkeypatch.setattr(
        "app.adapters.mock.directories.MockDirectoriesAdapter.discover", _no_directory_discover
    )
    tenant, user = _make_tenant(session)
    job = _make_job(session, tenant, user)
    session.commit()
    jid, tid = job.id, tenant.id
    try:

        def _boom(*_a, **_k):
            raise RuntimeError("validation exploded")

        monkeypatch.setattr("app.pipeline.stages.validate_all_pending", _boom)
        from app.pipeline.orchestrator import advance

        with pytest.raises(RuntimeError):
            advance(jid)  # runs on its own session; re-raises after marking FAILED

        session.expire_all()
        job = session.get(MiningJob, jid)
        assert job.status == JobStatus.FAILED
        assert job.completed_at is not None
        # Discovery + extraction data survived the later-stage crash.
        assert (
            session.scalar(select(func.count()).select_from(Company).where(Company.job_id == jid))
            > 0
        )
        assert (
            session.scalar(select(func.count()).select_from(Contact).where(Contact.job_id == jid))
            > 0
        )
        # Validation never finished, so no sales-ready leads leaked out.
        assert (
            session.scalar(
                select(func.count()).select_from(SalesReadyLead).where(SalesReadyLead.job_id == jid)
            )
            == 0
        )
    finally:
        session.rollback()
        session.delete(session.get(Tenant, tid))
        session.commit()


def test_sync_failure_is_nonfatal(
    session: Session, monkeypatch: pytest.MonkeyPatch, force_demo: None
):
    """A Google-Sheets error at the final sync must NOT fail the job — the mined
    data is already committed, so the job completes and the error is swallowed."""
    monkeypatch.setattr("app.adapters.mock.google_maps.MAPS_DEMO_LIMIT", SMALL_COMPANY_TARGET)
    monkeypatch.setattr(
        "app.adapters.mock.directories.MockDirectoriesAdapter.discover", _no_directory_discover
    )
    tenant, user = _make_tenant(session)
    job = _make_job(session, tenant, user)
    session.commit()
    jid, tid = job.id, tenant.id
    try:

        def _boom(*_a, **_k):
            raise RuntimeError("Google Sheets API 403 SERVICE_DISABLED")

        monkeypatch.setattr("app.pipeline.stages.run_sync", _boom)
        from app.pipeline.orchestrator import advance

        advance(jid)  # must NOT raise — _safe_sync swallows the sheet error

        session.expire_all()
        job = session.get(MiningJob, jid)
        assert job.status == JobStatus.COMPLETED
        assert job.progress_percent == 100
        assert (
            session.scalar(select(func.count()).select_from(Contact).where(Contact.job_id == jid))
            > 0
        )
    finally:
        session.rollback()
        session.delete(session.get(Tenant, tid))
        session.commit()
