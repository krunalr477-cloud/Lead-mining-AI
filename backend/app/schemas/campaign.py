"""Campaign / template / bounce / suppression API schemas (spec §13/§14/§19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.constants import TEMPLATE_VARIABLES

__all__ = [
    "BounceOut",
    "CampaignCreate",
    "CampaignDetail",
    "CampaignOut",
    "EligibilitySummary",
    "SuppressionCreate",
    "SuppressionOut",
    "TemplateCreate",
    "TemplateOut",
    "TemplateUpdate",
    "TestEmailRequest",
]


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=998)
    body: str | None = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    subject: str
    body: str
    created_by: uuid.UUID | None
    created_at: datetime


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subject_template: str = Field(min_length=1, max_length=998)
    body_template: str = Field(min_length=1)
    from_account: str = Field(min_length=3, max_length=320)
    job_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    rate_limit_per_hour: int = Field(default=100, ge=1, le=10000)
    rate_limit_per_day: int = Field(default=300, ge=1, le=100000)
    tracking_enabled: bool = True


class TrackingSettings(BaseModel):
    opens: bool
    clicks: bool
    replies: bool
    bounces: bool


class RateLimitSettings(BaseModel):
    per_hour: int
    per_day: int
    window_start: str | None = None
    window_end: str | None = None
    timezone: str | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    subject_template: str
    body_template: str
    from_account: str
    job_id: uuid.UUID | None
    template_id: uuid.UUID | None
    rate_limit_per_hour: int
    rate_limit_per_day: int
    tracking_enabled: bool
    status: str
    launched_at: datetime | None
    created_at: datetime

    # --- frontend-facing serialization ------------------------------------ #
    # The UI reads flat `subject`/`body`, an `ai_opener_enabled` flag, and
    # `tracking`/`rate_limit` objects. Emit them as computed fields so the wire
    # shape matches the client contract without renaming the stored columns.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def subject(self) -> str:
        return self.subject_template

    @computed_field  # type: ignore[prop-decorator]
    @property
    def body(self) -> str:
        return self.body_template

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ai_opener_enabled(self) -> bool:
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracking(self) -> TrackingSettings:
        on = self.tracking_enabled
        return TrackingSettings(opens=on, clicks=on, replies=on, bounces=on)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rate_limit(self) -> RateLimitSettings:
        return RateLimitSettings(per_hour=self.rate_limit_per_hour, per_day=self.rate_limit_per_day)


class CampaignStats(BaseModel):
    recipient_count: int = 0
    sent: int = 0
    delivered: int = 0
    opened: int = 0
    clicked: int = 0
    replied: int = 0
    bounced: int = 0
    queued: int = 0
    suppressed_skips: int = 0

    # --- frontend-facing serialization ------------------------------------ #
    # The UI reads `recipients` and per-metric rates (ratios 0..1). These are
    # computed on serialization so the stored/wire shape satisfies both the
    # campaign list and detail screens without a second field set.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def recipients(self) -> int:
        return self.recipient_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def suppressed(self) -> int:
        return self.suppressed_skips

    def _rate(self, numerator: int) -> float:
        base = self.sent or self.recipient_count
        return round(numerator / base, 4) if base else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def open_rate(self) -> float:
        return self._rate(self.opened)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def click_rate(self) -> float:
        return self._rate(self.clicked)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reply_rate(self) -> float:
        return self._rate(self.replied)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bounce_rate(self) -> float:
        return self._rate(self.bounced)


class EligibilitySummary(BaseModel):
    """Recipient-eligibility breakdown (spec §13 "Recipient eligibility summary")."""

    candidates: int
    eligible: int
    rejected: dict[str, int]


class CampaignDetail(CampaignOut):
    stats: CampaignStats
    eligibility: EligibilitySummary | None = None
    estimated_hours: float | None = None


class TestEmailRequest(BaseModel):
    to: EmailStr
    contact_id: uuid.UUID | None = Field(
        default=None, description="Render variables for this contact (optional)."
    )


class BounceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_message_id: uuid.UUID
    contact_id: uuid.UUID | None
    email: str
    smtp_status_code: str | None
    bounce_type: str
    diagnostic_code: str | None
    reason: str | None
    detected_at: datetime


class SuppressionCreate(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    domain: str | None = Field(default=None, max_length=255)
    reason: str | None = None
    permanent: bool = True


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str | None
    domain: str | None
    reason: str | None
    source: str | None
    permanent: bool
    created_at: datetime


# Exposed so the UI can render the variable-insertion menu.
TEMPLATE_VARIABLE_NAMES = list(TEMPLATE_VARIABLES)
