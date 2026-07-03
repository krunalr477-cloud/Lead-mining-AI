"""Per-tenant configuration: data-source compliance, validation rules, campaign limits."""

import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import DEFAULT_ROLE_KEYWORDS, AccessMethod, Posture, SourceName
from app.db import Base, TimestampMixin
from app.models._shared import UUIDPk, enum_check, uuid_fk

__all__ = ["CampaignSettings", "DataSourceConfig", "ValidationRuleSet"]


class DataSourceConfig(TimestampMixin, Base):
    __tablename__ = "data_source_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_name"),
        enum_check("source_name", SourceName),
        enum_check("compliance_posture", Posture),
        enum_check("access_method", AccessMethod),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE")
    source_name: Mapped[str] = mapped_column(String(50))
    # Safe-by-default: seeding enables green sources; amber/red stay off until sign-off.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_posture: Mapped[str] = mapped_column(String(10), default=Posture.AMBER)
    access_method: Mapped[str] = mapped_column(String(30), default=AccessMethod.MOCK)
    legal_note: Mapped[str | None] = mapped_column(Text)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    requires_signoff: Mapped[bool] = mapped_column(Boolean, default=False)
    signoff_user_id: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", ondelete="SET NULL", nullable=True, index=False
    )
    signoff_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    last_failure_at: Mapped[datetime | None]


def default_validation_rules() -> dict:
    """Spec §11 defaults; every key is tenant-editable from Validation Rules Settings."""
    return {
        "llm_threshold": 0.55,
        "llm_mode": "adjudicate",
        "role_keywords": list(DEFAULT_ROLE_KEYWORDS),
        "allow_role_based": False,
        "catch_all_policy": "review",
        "risk_policy": "review",
        "unknown_retry": 1,
    }


class ValidationRuleSet(TimestampMixin, Base):
    __tablename__ = "validation_rule_sets"

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", unique=True)
    rules: Mapped[dict] = mapped_column(JSONB, default=default_validation_rules)


class CampaignSettings(TimestampMixin, Base):
    __tablename__ = "campaign_settings"

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", unique=True)
    send_limit_per_hour: Mapped[int] = mapped_column(Integer, default=100)
    send_limit_per_day: Mapped[int] = mapped_column(Integer, default=300)
    send_window_start: Mapped[time] = mapped_column(Time, default=time(9, 0))
    send_window_end: Mapped[time] = mapped_column(Time, default=time(18, 0))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    unsubscribe_text: Mapped[str] = mapped_column(
        Text, default="If you'd prefer not to hear from us, reply with UNSUBSCRIBE."
    )
    executives_can_send: Mapped[bool] = mapped_column(Boolean, default=False)
