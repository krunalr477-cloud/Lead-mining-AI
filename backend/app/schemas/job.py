"""Mining-job request/response schemas (Pydantic v2) — spec §7 / §19."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants import JobStatus


class JobCreate(BaseModel):
    """Every spec §7 New-Mining-Job input. Only ``name`` is required."""

    name: str = Field(min_length=1, max_length=255)
    company_type: str | None = None
    services: list[str] = Field(default_factory=list)

    # Geography
    country: str | None = None
    state: str | None = None
    city: str | None = None
    zipcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None

    # Company size band (either bound optional).
    company_size_min: int | None = None
    company_size_max: int | None = None

    contact_roles: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    selected_sources: list[str] = Field(default_factory=list)

    # Enrichment / validation / output options (recorded on the job).
    enrichment_providers: list[str] = Field(default_factory=list)
    validation_stages: list[str] = Field(default_factory=list)
    output_options: list[str] = Field(default_factory=list)

    # Opt-in geo-tile sweep: 7 sub-circle Places searches per query variant —
    # beats the ~60-results/query cap; multiplies Places cost accordingly.
    deep_discovery: bool = False

    notes: str | None = None


class JobTotals(BaseModel):
    total_companies: int = 0
    total_contacts: int = 0
    emails_found: int = 0
    verified_emails: int = 0
    invalid_emails: int = 0
    review_emails: int = 0
    sales_ready_count: int = 0


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: JobStatus
    company_type: str | None
    services: list[str]
    country: str | None
    state: str | None
    city: str | None
    zipcode: str | None
    latitude: float | None
    longitude: float | None
    radius_km: float | None
    company_size_min: int | None
    company_size_max: int | None
    contact_roles: list[str]
    exclude_keywords: list[str]
    selected_sources: list[str]
    progress_percent: int
    totals_json: dict
    created_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    notes: str | None


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: JobStatus
    company_type: str | None
    city: str | None
    state: str | None
    country: str | None
    selected_sources: list[str]
    progress_percent: int
    totals_json: dict
    created_by: uuid.UUID | None
    created_at: datetime


class JobStartRequest(BaseModel):
    inline: bool = False


class ComplianceWarning(BaseModel):
    source: str
    posture: str
    message: str


class JobEstimate(BaseModel):
    estimated_companies_min: int
    estimated_companies_max: int
    estimated_cost_usd: float
    estimated_runtime_seconds: int
    compliance_warnings: list[ComplianceWarning]
    sheet_target: str
    selected_sources: list[str]
