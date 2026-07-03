"""Source adapter framework — the contract every data source implements.

Design rules (spec §8):
- Every adapter declares its compliance posture; the registry gates AMBER/RED
  sources behind admin enablement + sign-off + global env flags.
- Adapters never touch the network except through SourceRunContext helpers,
  so Data_Source_Audit coverage is structural, not voluntary.
- Real and mock implementations share one interface; mode is resolved per
  tenant/provider (DB credential -> env key -> mock) and recorded on SourceRun.
- A gated/unavailable source yields SourceUnavailable: the job logs a skipped
  SourceRun and CONTINUES (graceful failure, spec §8).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.constants import AccessMethod, HiringSignalType, Posture, SourceName

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext


@dataclass(slots=True)
class JobSpec:
    """Normalized mining-job filters handed to adapters."""

    job_id: UUID
    tenant_id: UUID
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


@dataclass(slots=True)
class DiscoveredCompany:
    """A normalized company candidate yielded by discover()."""

    name: str
    source_name: str
    source_url: str | None = None
    website: str | None = None
    domain: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    industry: str | None = None
    services: list[str] = field(default_factory=list)
    description: str | None = None
    company_size: str | None = None
    google_place_id: str | None = None
    google_rating: float | None = None
    google_reviews: int | None = None
    facebook_page_url: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    is_demo: bool = False


@dataclass(slots=True)
class ExtractedContact:
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    designation: str | None = None
    department: str | None = None
    seniority: str | None = None
    role_category: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    facebook_url: str | None = None
    source_page: str | None = None
    source_type: str | None = None
    source_snippet: str | None = None
    confidence_score: float = 0.5
    is_demo: bool = False


@dataclass(slots=True)
class ExtractedHiringSignal:
    source: str
    signal_type: HiringSignalType
    source_url: str | None = None
    job_title: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    description_excerpt: str | None = None
    confidence_score: float = 0.5


@dataclass(slots=True)
class ExtractionResult:
    """Deep-dive result for one company (contacts, signals, evidence)."""

    contacts: list[ExtractedContact] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    social_links: dict[str, str] = field(default_factory=dict)
    services: list[str] = field(default_factory=list)
    about_text: str | None = None
    hiring_signals: list[ExtractedHiringSignal] = field(default_factory=list)
    pages_crawled: list[str] = field(default_factory=list)
    website_status: str | None = None

    @classmethod
    def empty(cls) -> ExtractionResult:
        return cls()


@dataclass(slots=True)
class CompanyRef:
    """Reference to a stored company for extract()."""

    company_id: UUID
    name: str
    website: str | None
    domain: str | None
    city: str | None
    country: str | None


@dataclass(slots=True)
class SourceUnavailable:
    """Returned by the registry when a source cannot run. The job continues."""

    source_name: str
    reason: str
    posture: Posture


@dataclass(slots=True)
class HealthResult:
    ok: bool
    detail: str = ""


class SourceAdapter(ABC):
    """One data source (real or mock). Class attributes are the source card."""

    name: SourceName
    source_type: str  # "places_api" | "crawler" | "provider_api" | "serp" | "graph_api"
    access_method: AccessMethod
    posture: Posture
    default_enabled: bool
    requires_signoff: bool
    required_credentials: list[str] = []
    legal_note: str = ""

    async def health_check(self, ctx: SourceRunContext) -> HealthResult:
        return HealthResult(ok=True)

    @abstractmethod
    def discover(self, job: JobSpec, ctx: SourceRunContext) -> AsyncIterator[DiscoveredCompany]:
        """Yield normalized company candidates matching the job filters."""

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        """Optional per-company deep dive (contacts/emails/signals)."""
        return ExtractionResult.empty()


class EnrichmentAdapter(ABC):
    """Contact enrichment provider (RocketReach or mock)."""

    provider: str
    required_credentials: list[str] = []

    @abstractmethod
    async def enrich(
        self,
        *,
        company_name: str,
        domain: str | None,
        website: str | None,
        person_name: str | None,
        designation: str | None,
        location: str | None,
        ctx: SourceRunContext,
    ) -> list[ExtractedContact]:
        """Return enriched contact candidates (may include extra contacts)."""


class EmailVerifierAdapter(ABC):
    """Final paid verification provider (MillionVerifier or mock)."""

    provider: str
    required_credentials: list[str] = []

    @abstractmethod
    async def verify(self, email: str, ctx: SourceRunContext) -> tuple[str, dict[str, Any]]:
        """Return (MillionVerifierStatus value, raw provider payload)."""


class LLMScorerAdapter(ABC):
    """Suspicious-email-pattern scorer (Groq or heuristic mock)."""

    provider: str
    required_credentials: list[str] = []

    @abstractmethod
    async def score(self, emails: list[str], ctx: SourceRunContext) -> list[tuple[str, float, str]]:
        """Return [(email, score 0..1, reason)] for a batch."""
