"""Settings / admin API schemas (Pydantic v2).

These back the five Settings screens (spec §17):
- ``/settings``          — tenant campaign/send-window settings blob
- ``/sources``           — data-source compliance rows (+ patch/signoff)
- ``/integrations``      — provider connection cards (+ test)
- ``/validation-rules``  — the knobs gating Sales_Ready_Leads
- ``/audit``             — the mutation ledger

The validation-rules view deliberately exposes *frontend* field names
(``role_based_keywords`` / ``catch_all_handling`` / …) which differ from the
keys the pipeline reads off the JSONB (``role_keywords`` / ``catch_all_policy``
/ …). The router maps between the two so neither side has to change contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuditEntryOut",
    "DataSourceOut",
    "EnvKeyOut",
    "EnvKeyReveal",
    "EnvKeyRevealRequest",
    "EnvKeyUpdate",
    "IntegrationOut",
    "IntegrationSecretInput",
    "IntegrationTestResult",
    "SettingsOut",
    "SettingsPatch",
    "SourcePatch",
    "ValidationRulesOut",
    "ValidationRulesPatch",
]


# --------------------------------------------------------------------------- #
# /settings — tenant campaign / send-window blob
# --------------------------------------------------------------------------- #


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    send_limit_per_hour: int
    send_limit_per_day: int
    send_window_start: time
    send_window_end: time
    timezone: str
    unsubscribe_text: str
    executives_can_send: bool


class SettingsPatch(BaseModel):
    send_limit_per_hour: int | None = Field(default=None, ge=1, le=100000)
    send_limit_per_day: int | None = Field(default=None, ge=1, le=1000000)
    send_window_start: time | None = None
    send_window_end: time | None = None
    timezone: str | None = Field(default=None, max_length=64)
    unsubscribe_text: str | None = None
    executives_can_send: bool | None = None


# --------------------------------------------------------------------------- #
# /sources — data-source compliance
# --------------------------------------------------------------------------- #


class DataSourceOut(BaseModel):
    name: str
    display_name: str | None = None
    source_type: str | None = None
    access_method: str | None = None
    posture: str
    enabled: bool
    legal_note: str | None = None
    requires_signoff: bool = False
    signed_off: bool = False
    signed_off_by: str | None = None
    signed_off_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    rate_limit: str | None = None


class SourcePatch(BaseModel):
    enabled: bool | None = None


# --------------------------------------------------------------------------- #
# /integrations — provider connection cards
# --------------------------------------------------------------------------- #


class IntegrationOut(BaseModel):
    provider: str
    display_name: str | None = None
    status: str  # "live" | "mock" | "not_configured"
    masked_key: str | None = None
    last_verified_at: datetime | None = None
    note: str | None = None
    scopes: list[str] | None = None


class IntegrationTestResult(BaseModel):
    ok: bool
    provider: str
    status: str
    message: str | None = None
    latency_ms: int | None = None


class IntegrationSecretInput(BaseModel):
    """Body for PUT /integrations/{provider} — a per-provider secret.

    A single ``api_key`` covers most providers; ``google_oauth`` supplies
    ``client_id`` + ``client_secret``; a licensed provider may add a ``base_url``.
    All fields are optional on the wire so one shape serves every card; the
    router validates the required subset per provider and 422s on a mismatch.
    Secret fields are constrained in length but never echoed back.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: str | None = Field(default=None, max_length=4096)
    client_id: str | None = Field(default=None, max_length=4096)
    client_secret: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=2048)


# --------------------------------------------------------------------------- #
# /validation-rules — frontend-shaped view over the JSONB rule set
# --------------------------------------------------------------------------- #


class ValidationRulesOut(BaseModel):
    disposable_domains: list[str]
    role_based_keywords: list[str]
    llm_threshold: float
    catch_all_handling: str
    risk_handling: str
    unknown_retry_policy: str


class ValidationRulesPatch(BaseModel):
    disposable_domains: list[str] | None = None
    role_based_keywords: list[str] | None = None
    llm_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    catch_all_handling: str | None = None
    risk_handling: str | None = None
    unknown_retry_policy: str | None = None


# --------------------------------------------------------------------------- #
# /audit — mutation ledger
# --------------------------------------------------------------------------- #


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    actor: str | None = None
    actor_name: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    before: Any | None = None
    after: Any | None = None
    created_at: datetime


# --------------------------------------------------------------------------- #
# /settings/env-keys — the .env single-source-of-truth key manager
# --------------------------------------------------------------------------- #


class EnvKeyOut(BaseModel):
    """One managed ``.env`` key as rendered on the Settings screen.

    Secrets are never returned in the clear here: ``value`` is populated only for
    non-secret config; secrets expose ``masked`` (``****last4``) when set and are
    only revealed through the dedicated, audited reveal endpoint.
    """

    key: str
    label: str
    group: str  # "Google" | "Microsoft" | "Providers" | "Runtime"
    is_secret: bool
    is_set: bool
    masked: str | None = None  # ****last4, for set secrets
    value: str | None = None  # plaintext for non-secret config only
    source: str  # "env" | "unset"


class EnvKeyUpdate(BaseModel):
    """Body for PUT /settings/env-keys — a map of managed KEY -> new value."""

    model_config = ConfigDict(str_strip_whitespace=False)

    values: dict[str, str] = Field(default_factory=dict)


class EnvKeyRevealRequest(BaseModel):
    """Body for POST /settings/env-keys/reveal — the single key to reveal."""

    key: str


class EnvKeyReveal(BaseModel):
    """The full current value of one managed key (admin-only, audited)."""

    key: str
    value: str
