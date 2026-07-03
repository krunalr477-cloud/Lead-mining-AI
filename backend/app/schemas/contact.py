"""Contact + validation request/response schemas (Pydantic v2) — spec §19."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ValidationCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_candidate_id: uuid.UUID
    contact_id: uuid.UUID
    company_id: uuid.UUID | None
    syntax_status: str
    disposable_status: str
    role_based_status: str
    mx_status: str
    llm_score: Decimal | None
    llm_reason: str | None
    millionverifier_status: str | None
    final_status: str | None
    final_reason: str | None
    retry_count: int
    verified_at: datetime | None
    created_at: datetime


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    job_id: uuid.UUID | None
    full_name: str | None
    first_name: str | None
    last_name: str | None
    designation: str | None
    department: str | None
    seniority: str | None
    role_category: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None
    facebook_url: str | None
    source_type: str | None
    confidence_score: Decimal | None
    primary_contact: bool
    enrichment_status: str
    enrichment_provider: str | None
    final_email_status: str | None
    last_verified_at: datetime | None
    sales_ready: bool
    owner_user_id: uuid.UUID | None
    notes: str | None
    created_at: datetime


class ContactDetail(ContactOut):
    validation_checks: list[ValidationCheckOut] = []


class ContactPatch(BaseModel):
    # Sales-editable fields only (owner/notes/next_action -> mirrored to sheet).
    owner_user_id: uuid.UUID | None = None
    notes: str | None = None
    next_action: str | None = None


class ValidationRunRequest(BaseModel):
    contact_ids: list[uuid.UUID] = []
    email_candidate_ids: list[uuid.UUID] = []


class ValidationRunResult(BaseModel):
    validated: int
    checks: list[ValidationCheckOut]
