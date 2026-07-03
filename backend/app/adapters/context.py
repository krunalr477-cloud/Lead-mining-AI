"""SourceRunContext — the sole conduit between an adapter and the outside world.

One context is constructed per (job, source) before the adapter runs. It owns:
- a SourceRun row (opened here, closed by finalize())
- a sync DB Session and a Redis client (workers are sync — spec §4)
- structural audit: every network touch flows through audit(), so
  Data_Source_Audit coverage is guaranteed by construction, not discipline
- metered usage: record_usage() upserts an APIUsage row per provider call
- a rate_limiter handle for the adapter to throttle real network access

Adapters never import a DB session or Redis directly; they receive this object
and call its helpers. Mock adapters use audit()/record_usage() too so the demo
run produces the same audit/usage trail a real run would.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.constants import AccessMethod, Posture, SourceRunStatus
from app.db import utcnow
from app.models import APIUsage, DataSourceAuditEvent, SourceRun

if TYPE_CHECKING:
    import redis
    from sqlalchemy.orm import Session

    from app.workers.rate_limit import CompositeBucket, TokenBucket

__all__ = ["SourceRunContext"]


class SourceRunContext:
    """Per-(job, source) execution context. Sync only (Celery worker path)."""

    def __init__(
        self,
        *,
        session: Session,
        redis_client: redis.Redis,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        source_name: str,
        source_type: str,
        access_method: AccessMethod,
        posture: Posture,
        rate_limiter: TokenBucket | CompositeBucket | None = None,
    ) -> None:
        self.session = session
        self.redis = redis_client
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.source_name = source_name
        self.source_type = source_type
        self.access_method = access_method
        self.posture = posture
        self.rate_limiter = rate_limiter
        self._source_run: SourceRun | None = None

    # -- SourceRun lifecycle ------------------------------------------------

    def open(self) -> SourceRun:
        """Create (or reuse) the SourceRun row and mark it RUNNING.

        Idempotent within a context: repeated calls return the same row.
        """
        if self._source_run is not None:
            return self._source_run
        run = SourceRun(
            job_id=self.job_id,
            source_name=self.source_name,
            access_method=str(self.access_method),
            compliance_posture=str(self.posture),
            status=SourceRunStatus.RUNNING,
            started_at=utcnow(),
        )
        self.session.add(run)
        self.session.flush()  # populate run.id for audit FK linkage
        self._source_run = run
        return run

    @property
    def source_run(self) -> SourceRun:
        return self.open()

    @property
    def source_run_id(self) -> uuid.UUID | None:
        return self._source_run.id if self._source_run is not None else None

    # -- Structural audit ---------------------------------------------------

    def audit(
        self,
        url: str | None,
        status: str,
        *,
        records_found: int = 0,
        error: str | None = None,
    ) -> DataSourceAuditEvent:
        """Record one raw source touch (an endpoint hit or a page fetch).

        Called by adapters around every outbound access so Data_Source_Audit
        stays complete. Flushes but does not commit — the worker owns the txn.
        """
        event = DataSourceAuditEvent(
            tenant_id=self.tenant_id,
            job_id=self.job_id,
            source_run_id=self.source_run_id,
            source_name=self.source_name,
            source_type=self.source_type,
            access_method=str(self.access_method),
            compliance_posture=str(self.posture),
            url_or_endpoint=url,
            status=status,
            records_found=records_found,
            error_message=error,
        )
        self.session.add(event)
        self.session.flush()
        return event

    # -- Metered usage ------------------------------------------------------

    def record_usage(
        self,
        provider: str,
        endpoint: str,
        unit_cost: float | Decimal | None,
        request_count: int = 1,
    ) -> APIUsage:
        """Accumulate provider API usage for this tenant.

        Upserts by (tenant, provider, endpoint): a matching row this run has its
        request_count and estimated_cost incremented; otherwise a new row opens.
        """
        cost = None if unit_cost is None else Decimal(str(unit_cost))
        row = self.session.execute(
            select(APIUsage)
            .where(
                APIUsage.tenant_id == self.tenant_id,
                APIUsage.provider == provider,
                APIUsage.endpoint == endpoint,
            )
            .order_by(APIUsage.measured_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        added = None if cost is None else cost * request_count
        if row is None:
            row = APIUsage(
                tenant_id=self.tenant_id,
                provider=provider,
                endpoint=endpoint,
                request_count=request_count,
                unit_cost=cost,
                estimated_cost=added,
                measured_at=utcnow(),
            )
            self.session.add(row)
        else:
            row.request_count += request_count
            if cost is not None:
                row.unit_cost = cost
                prior = row.estimated_cost or Decimal("0")
                row.estimated_cost = prior + (added or Decimal("0"))
            row.measured_at = utcnow()
        self.session.flush()
        return row

    # -- Close --------------------------------------------------------------

    def finalize(
        self,
        status: SourceRunStatus | str,
        records_found: int = 0,
        records_imported: int = 0,
        error: str | None = None,
    ) -> SourceRun:
        """Close the SourceRun with terminal counts and status."""
        run = self.open()
        run.status = str(status)
        run.records_found = records_found
        run.records_imported = records_imported
        run.completed_at = utcnow()
        if error is not None:
            run.error_message = error
            run.last_error = error
        self.session.flush()
        return run

    # -- Convenience --------------------------------------------------------

    def raw(self) -> dict[str, Any]:
        """Small context snapshot (handy for CompanySource.raw_payload)."""
        return {
            "source_name": self.source_name,
            "access_method": str(self.access_method),
            "compliance_posture": str(self.posture),
            "job_id": str(self.job_id),
        }
