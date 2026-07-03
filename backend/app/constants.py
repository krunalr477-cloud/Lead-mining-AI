"""Shared enums and constants. String enums stored as VARCHAR + CHECK constraints."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    SALES_MANAGER = "sales_manager"
    SALES_EXECUTIVE = "sales_executive"
    VIEWER = "viewer"


class JobStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(StrEnum):
    RESOLVING_LOCATION = "resolving_location"
    DISCOVERING = "discovering"
    DEDUPING = "deduping"
    CRAWLING = "crawling"
    EXTRACTING = "extracting"
    ENRICHING = "enriching"
    VALIDATING = "validating"
    SYNCING = "syncing"
    SALES_READY = "sales_ready"
    DONE = "done"


class Posture(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class SourceName(StrEnum):
    GOOGLE_MAPS = "google_maps"
    COMPANY_WEBSITES = "company_websites"
    DIRECTORIES = "directories"
    YELLOW_PAGES = "yellow_pages"
    CLUTCH = "clutch"
    FACEBOOK_SIGNALS = "facebook_signals"
    SERP_JOBS = "serp_jobs"
    INDEED = "indeed"
    LINKEDIN = "linkedin"


class SourceRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AccessMethod(StrEnum):
    OFFICIAL_API = "official_api"
    HTTP_CRAWL = "http_crawl"
    LICENSED_PROVIDER = "licensed_provider"
    SERP = "serp"
    MOCK = "mock"


class FinalEmailStatus(StrEnum):
    VERIFIED = "VERIFIED"
    INVALID_SYNTAX = "INVALID_SYNTAX"
    DISPOSABLE_REJECTED = "DISPOSABLE_REJECTED"
    ROLE_BASED_REJECTED = "ROLE_BASED_REJECTED"
    MX_FAILED = "MX_FAILED"
    LLM_LOW_CONFIDENCE = "LLM_LOW_CONFIDENCE"
    PROVIDER_INVALID = "PROVIDER_INVALID"
    CATCH_ALL_REVIEW = "CATCH_ALL_REVIEW"
    RISK_REVIEW = "RISK_REVIEW"
    UNKNOWN_RETRY = "UNKNOWN_RETRY"
    SUPPRESSED = "SUPPRESSED"


class StageStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    SKIPPED = "skipped"
    PENDING = "pending"


class MillionVerifierStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    RISK = "risk"
    UNKNOWN = "unknown"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    SENDING = "sending"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    HARD_BOUNCE = "hard_bounce"
    SOFT_BOUNCE = "soft_bounce"
    BLOCKED = "blocked"
    SPAM_COMPLAINT = "spam_complaint"
    UNSUBSCRIBED = "unsubscribed"


class BounceType(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    MAILBOX_FULL = "mailbox_full"
    INVALID_DOMAIN = "invalid_domain"
    BLOCKED = "blocked"
    SPAM_REJECTED = "spam_rejected"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class EnrichmentStatus(StrEnum):
    NOT_NEEDED = "not_needed"
    PENDING = "pending"
    ENRICHED = "enriched"
    NO_RESULT = "no_result"
    FAILED = "failed"


class SyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"


class ExportFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class HiringSignalType(StrEnum):
    JOB_POSTING = "job_posting"
    CAREERS_PAGE = "careers_page"
    PUBLIC_POST = "public_post"


# Default role-inbox keywords (spec §11 stage 3) — tenant-configurable.
DEFAULT_ROLE_KEYWORDS = [
    "info",
    "support",
    "sales",
    "admin",
    "careers",
    "jobs",
    "hr",
    "marketing",
    "contact",
    "hello",
]

# The 12 Celery queues (spec §4).
QUEUES = [
    "google_maps_jobs",
    "website_scrape_jobs",
    "directory_source_jobs",
    "facebook_signal_jobs",
    "job_signal_jobs",
    "enrichment_jobs",
    "validation_jobs",
    "spreadsheet_sync_jobs",
    "campaign_jobs",
    "bounce_check_jobs",
    "export_jobs",
    "audit_jobs",
]

# Template variables available in campaign templates (spec §13).
TEMPLATE_VARIABLES = [
    "FirstName",
    "LastName",
    "FullName",
    "Company",
    "Industry",
    "City",
    "State",
    "Country",
    "Services",
    "Designation",
    "Website",
    "HiringSignal",
]
