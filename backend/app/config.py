"""Application settings, loaded from environment / .env at repo root."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class AdapterMode(StrEnum):
    AUTO = "auto"
    REAL = "real"
    MOCK = "mock"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    database_url: str = "postgresql+psycopg://leadmine:leadmine@127.0.0.1:5432/leadmine"
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret: str = "dev-only-secret-change-me"
    app_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    environment: str = "development"
    demo_mode: bool = True

    # Google
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    google_maps_api_key: str = ""
    google_sheets_scopes: str = "https://www.googleapis.com/auth/spreadsheets"
    gmail_scopes: str = (
        "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
    )

    # Microsoft (Outlook / Entra ID) — sign-in only
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant: str = "common"  # "common" | "organizations" | a directory (tenant) id
    microsoft_redirect_uri: str = "http://localhost:8000/api/v1/auth/microsoft/callback"
    microsoft_scopes: str = "openid email profile offline_access User.Read"

    # Providers
    rocketreach_api_key: str = ""
    millionverifier_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    serp_provider: str = "serpapi"
    serp_api_key: str = ""

    # Object storage (empty => local-disk export driver)
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # Security & policy
    encryption_key: str = ""
    default_send_limit_per_hour: int = 100
    default_send_limit_per_day: int = 300
    bounce_poll_interval_minutes: int = 30
    validation_llm_threshold: float = 0.55
    enable_facebook_signals: bool = False
    enable_linkedin_connector: bool = False
    enable_compliance_gated_sources: bool = False

    # Adapter mode
    adapter_mode: AdapterMode = AdapterMode.AUTO

    # Crawler
    crawler_max_pages_per_domain: int = 8
    crawler_per_domain_delay_seconds: float = 2.0

    # Sheets sync
    sheets_writes_per_minute: int = 50

    # Provider rate limits (per tenant, per minute) — paced through a token bucket
    # so enrichment/validation don't hammer a provider into 429s.
    enrichment_lookups_per_minute: int = 30
    verifier_checks_per_minute: int = 60
    llm_scores_per_minute: int = 60

    @property
    def sync_database_url(self) -> str:
        """psycopg (sync) URL for Celery workers and Alembic."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    @property
    def async_database_url(self) -> str:
        """asyncpg URL for the FastAPI app."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")

    def source_mode_override(self, source_name: str) -> AdapterMode | None:
        """Per-source env override, e.g. SOURCE_GOOGLE_MAPS_MODE=real."""
        import os

        raw = os.environ.get(f"SOURCE_{source_name.upper()}_MODE")
        return AdapterMode(raw) if raw else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
