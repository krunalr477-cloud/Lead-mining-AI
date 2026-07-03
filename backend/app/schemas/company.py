"""Company request/response schemas (Pydantic v2) — spec §19."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CompanySourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    source_url: str | None
    access_method: str
    compliance_posture: str
    first_seen_at: datetime


class HiringSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    source_url: str | None
    job_title: str | None
    location: str | None
    posted_at: datetime | None
    signal_type: str
    confidence_score: Decimal | None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID | None
    canonical_name: str
    website: str | None
    domain: str | None
    phone: str | None
    address: str | None
    city: str | None
    state: str | None
    country: str | None
    postal_code: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    industry: str | None
    services: list[str]
    company_size: str | None
    google_rating: Decimal | None
    google_reviews: int | None
    facebook_page_url: str | None
    source_urls: list[str]
    dedupe_status: str
    website_status: str | None
    hiring_signal_status: str | None
    compliance_posture: str | None
    last_refreshed_at: datetime | None
    created_at: datetime


class ContactBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str | None
    designation: str | None
    role_category: str | None
    email: str | None
    final_email_status: str | None
    primary_contact: bool
    sales_ready: bool


class CompanyDetail(CompanyOut):
    contacts: list[ContactBrief] = []
    sources: list[CompanySourceOut] = []
    hiring_signals: list[HiringSignalOut] = []


class CompanyPatch(BaseModel):
    canonical_name: str | None = None
    website: str | None = None
    phone: str | None = None
    industry: str | None = None
    company_size: str | None = None
    notes: str | None = None
