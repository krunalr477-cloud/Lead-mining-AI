"""Auth and user-management schemas (Pydantic v2)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.config import Settings, get_settings
from app.constants import Role

# Provider name -> settings attribute(s) that must ALL be non-empty for "live".
_PROVIDER_KEYS: dict[str, tuple[str, ...]] = {
    "google_maps": ("google_maps_api_key",),
    "rocketreach": ("rocketreach_api_key",),
    "millionverifier": ("millionverifier_api_key",),
    "groq": ("groq_api_key",),
    "serp": ("serp_api_key",),
    "gmail": ("google_client_id", "google_client_secret"),
    "sheets": ("google_client_id", "google_client_secret"),
}


def provider_modes(settings: Settings | None = None) -> dict[str, str]:
    """ "live" or "mock" per provider: mock when DEMO_MODE or the key is empty."""
    settings = settings or get_settings()
    return {
        provider: (
            "mock"
            if settings.demo_mode or not all(getattr(settings, key) for key in keys)
            else "live"
        )
        for provider, keys in _PROVIDER_KEYS.items()
    }


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: Role
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut
    demo_mode: bool
    providers: dict[str, str]


class UserInvite(BaseModel):
    email: EmailStr
    name: str
    role: Role = Role.SALES_EXECUTIVE


class UserPatch(BaseModel):
    name: str | None = None
    role: Role | None = None
