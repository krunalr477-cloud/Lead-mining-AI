"""Batch-9: GET /jobs/{id}/sources aggregation (route function called directly
over a real async session — no HTTP harness needed; auth deps are bypassed by
passing the actor placeholder, tenancy is asserted via the 404 path).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.jobs import job_sources
from app.config import get_settings
from app.constants import JobStatus, Role
from app.models import MiningJob, SourceRun, Tenant, User

pytestmark = pytest.mark.integration


def _run(coro_fn) -> None:
    async def _main() -> None:
        engine = create_async_engine(get_settings().async_database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            await coro_fn(factory)
        finally:
            await engine.dispose()

    asyncio.run(_main())


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = Tenant(name=f"src-api-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        name="T",
        email=f"t-{tenant.id}@leadmine.local",
        role=Role.ADMIN,
    )
    session.add(user)
    await session.flush()
    job = MiningJob(
        tenant_id=tenant.id, created_by=user.id, name="src agg", status=JobStatus.COMPLETED
    )
    session.add(job)
    await session.flush()
    runs = [
        SourceRun(
            job_id=job.id, source_name="google_maps", access_method="official_api",
            compliance_posture="green", status="completed", records_found=60,
            records_imported=58,
        ),
        SourceRun(
            job_id=job.id, source_name="company_websites", access_method="http_crawl",
            compliance_posture="green", status="completed", records_found=5,
            records_imported=4, retry_count=1,
        ),
        SourceRun(
            job_id=job.id, source_name="company_websites", access_method="http_crawl",
            compliance_posture="green", status="failed", records_found=0,
            records_imported=0, error_message="boom",
        ),
        SourceRun(
            job_id=job.id, source_name="directories", access_method="mock",
            compliance_posture="green", status="skipped", records_found=0,
            records_imported=0,
        ),
    ]
    session.add_all(runs)
    await session.commit()
    return tenant.id, job.id


def test_job_sources_aggregates_per_source() -> None:
    async def scenario(factory) -> None:
        async with factory() as session:
            tid, jid = await _seed(session)
        try:
            async with factory() as session:
                out = await job_sources(jid, None, tid, session)
                by_name = {s.source_name: s for s in out}
                assert set(by_name) == {"google_maps", "company_websites", "directories"}
                cw = by_name["company_websites"]
                assert cw.runs == 2
                assert cw.completed == 1 and cw.failed == 1
                assert cw.records_found == 5 and cw.records_imported == 4
                assert cw.retries == 1
                assert cw.last_error == "boom"
                gm = by_name["google_maps"]
                assert gm.records_found == 60 and gm.failed == 0
                assert by_name["directories"].skipped == 1

                # Tenancy: a different tenant gets a 404, not data.
                with pytest.raises(HTTPException) as ei:
                    await job_sources(jid, None, uuid.uuid4(), session)
                assert ei.value.status_code == 404
        finally:
            async with factory() as session:
                t = await session.get(Tenant, tid)
                if t is not None:
                    await session.delete(t)
                    await session.commit()

    _run(scenario)
