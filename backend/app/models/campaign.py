"""Outreach aggregate: templates, campaigns, messages, bounces, replies, suppression."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import BounceType, CampaignStatus, MessageStatus
from app.db import Base, TimestampMixin, utcnow
from app.models._shared import UUIDPk, enum_check, uuid_fk

__all__ = [
    "BounceEvent",
    "Campaign",
    "EmailMessage",
    "EmailTemplate",
    "ReplyEvent",
    "Suppression",
]


class EmailTemplate(TimestampMixin, Base):
    __tablename__ = "email_templates"

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(998))
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", ondelete="SET NULL", nullable=True, index=False
    )


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_tenant_id_created_at", "tenant_id", "created_at"),
        enum_check("status", CampaignStatus),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    created_by: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", ondelete="SET NULL", nullable=True, index=False
    )
    job_id: Mapped[uuid.UUID | None] = uuid_fk("mining_jobs.id", ondelete="SET NULL", nullable=True)
    template_id: Mapped[uuid.UUID | None] = uuid_fk(
        "email_templates.id", ondelete="SET NULL", nullable=True, index=False
    )
    name: Mapped[str] = mapped_column(String(255))
    subject_template: Mapped[str] = mapped_column(String(998))
    body_template: Mapped[str] = mapped_column(Text)
    from_account: Mapped[str] = mapped_column(String(320))
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=100)
    rate_limit_per_day: Mapped[int] = mapped_column(Integer, default=300)
    tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT)
    launched_at: Mapped[datetime | None]

    template: Mapped[EmailTemplate | None] = relationship()
    messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True
    )


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        Index("ix_email_messages_campaign_id_status", "campaign_id", "status"),
        enum_check("status", MessageStatus),
    )

    id: Mapped[UUIDPk]
    campaign_id: Mapped[uuid.UUID] = uuid_fk("campaigns.id", ondelete="CASCADE", index=False)
    contact_id: Mapped[uuid.UUID | None] = uuid_fk(
        "contacts.id", ondelete="SET NULL", nullable=True
    )
    to_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str] = mapped_column(String(998))
    body: Mapped[str] = mapped_column(Text)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default=MessageStatus.QUEUED)
    scheduled_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    opened_at: Mapped[datetime | None]
    clicked_at: Mapped[datetime | None]
    replied_at: Mapped[datetime | None]
    bounced_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="messages")
    bounce_events: Mapped[list["BounceEvent"]] = relationship(
        back_populates="email_message", cascade="all, delete-orphan", passive_deletes=True
    )
    reply_events: Mapped[list["ReplyEvent"]] = relationship(
        back_populates="email_message", cascade="all, delete-orphan", passive_deletes=True
    )


class BounceEvent(Base):
    __tablename__ = "bounce_events"
    __table_args__ = (enum_check("bounce_type", BounceType),)

    id: Mapped[UUIDPk]
    email_message_id: Mapped[uuid.UUID] = uuid_fk("email_messages.id", ondelete="CASCADE")
    contact_id: Mapped[uuid.UUID | None] = uuid_fk(
        "contacts.id", ondelete="SET NULL", nullable=True, index=False
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    smtp_status_code: Mapped[str | None] = mapped_column(String(20))
    bounce_type: Mapped[str] = mapped_column(String(20), default=BounceType.UNKNOWN)
    diagnostic_code: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    raw_message_reference: Mapped[str | None] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(default=utcnow)

    email_message: Mapped[EmailMessage] = relationship(back_populates="bounce_events")


class ReplyEvent(Base):
    __tablename__ = "reply_events"

    id: Mapped[UUIDPk]
    email_message_id: Mapped[uuid.UUID] = uuid_fk("email_messages.id", ondelete="CASCADE")
    contact_id: Mapped[uuid.UUID | None] = uuid_fk(
        "contacts.id", ondelete="SET NULL", nullable=True, index=False
    )
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    snippet: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(default=utcnow)

    email_message: Mapped[EmailMessage] = relationship(back_populates="reply_events")


class Suppression(Base):
    __tablename__ = "suppressions"
    __table_args__ = (
        Index("ix_suppressions_tenant_id_email", "tenant_id", "email"),
        Index("ix_suppressions_tenant_id_domain", "tenant_id", "domain"),
    )

    id: Mapped[UUIDPk]
    tenant_id: Mapped[uuid.UUID] = uuid_fk("tenants.id", ondelete="CASCADE", index=False)
    # Either a single address or a whole domain (at least one is set).
    email: Mapped[str | None] = mapped_column(String(320))
    domain: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(100))
    permanent: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
