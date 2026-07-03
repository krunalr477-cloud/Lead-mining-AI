"""JWT session tokens and Google OAuth sign-in.

Tokens are HS256 JWTs (7-day expiry) carried in the ``lm_session`` httpOnly
cookie or an ``Authorization: Bearer`` header. Google sign-in uses the
google-auth-oauthlib ``Flow`` with offline access so we always receive a
refresh token, which is stored Fernet-encrypted in IntegrationCredential.
"""

import os
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import jwt
from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import Role
from app.db import utcnow
from app.models import IntegrationCredential, Tenant, User
from app.security.crypto import get_cipher

SESSION_COOKIE_NAME = "lm_session"
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=7)

# Full URLs (not the "email"/"profile" aliases) so the scopes Google echoes
# back match what we requested and oauthlib does not flag a scope change.
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GOOGLE_PROVIDER = "google"


# --------------------------------------------------------------------------- JWT


def issue_token(user: User) -> str:
    """Signed session JWT for a persisted user row."""
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": str(user.role),
        "email": user.email,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and validate a session JWT. Raises jwt.InvalidTokenError."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )


# ------------------------------------------------------------------- Google OAuth


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    """Verified identity extracted from a Google OAuth code exchange."""

    subject: str
    email: str
    name: str
    workspace_domain: str | None  # the ``hd`` claim; None for consumer accounts
    refresh_token: str | None
    granted_scopes: list[str] = field(default_factory=list)


def _build_flow() -> Flow:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth not configured",
        )
    # Google reorders/expands granted scopes; don't let oauthlib treat that as
    # an error. In development the redirect URI is plain http://localhost.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    if settings.environment == "development":
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=GOOGLE_OAUTH_SCOPES,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def build_authorization_url() -> str:
    """Google consent-screen URL requesting offline access (refresh token)."""
    flow = _build_flow()
    authorization_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def exchange_code(code: str) -> GoogleIdentity:
    """Blocking code exchange + id_token verification.

    Call from async routes via ``run_in_threadpool``.
    """
    settings = get_settings()
    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as exc:  # oauthlib raises a zoo of error types
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth code exchange failed: {exc.__class__.__name__}",
        ) from exc

    credentials = flow.credentials
    try:
        claims = google_id_token.verify_oauth2_token(
            credentials.id_token,
            google_requests.Request(),
            settings.google_client_id,
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google id_token verification failed",
        ) from exc

    email = (claims.get("email") or "").lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account has no email claim",
        )
    return GoogleIdentity(
        subject=claims["sub"],
        email=email,
        name=claims.get("name") or email.split("@")[0],
        workspace_domain=claims.get("hd"),
        refresh_token=credentials.refresh_token,
        granted_scopes=list(credentials.scopes or []),
    )


async def upsert_google_user(session: AsyncSession, identity: GoogleIdentity) -> User:
    """Tenant/User upsert for a verified Google identity.

    - Returning user (matched on google_oauth_subject): refresh profile fields.
    - First user of a Workspace domain: new tenant named after the domain,
      role=admin. Consumer accounts (no ``hd``) get a "My Workspace" tenant.
    - Subsequent users on the same google_workspace_domain join as
      sales_executive (or claim a pre-invited row matched by email).
    - The Google refresh token is stored Fernet-encrypted per tenant in
      IntegrationCredential(provider="google").
    """
    user = (
        await session.execute(select(User).where(User.google_oauth_subject == identity.subject))
    ).scalar_one_or_none()

    if user is not None:
        user.name = identity.name or user.name
        user.email = identity.email or user.email
    else:
        tenant: Tenant | None = None
        if identity.workspace_domain:
            tenant = (
                await session.execute(
                    select(Tenant).where(
                        Tenant.google_workspace_domain == identity.workspace_domain
                    )
                )
            ).scalar_one_or_none()

        if tenant is None:
            tenant = Tenant(
                name=identity.workspace_domain or "My Workspace",
                google_workspace_domain=identity.workspace_domain,
            )
            session.add(tenant)
            await session.flush()
            default_role = Role.ADMIN  # first user of a tenant is its admin
        else:
            default_role = Role.SALES_EXECUTIVE

        # A user may have been invited by email before their first login.
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.email == identity.email)
            )
        ).scalar_one_or_none()
        if user is not None:
            user.google_oauth_subject = identity.subject
            user.name = identity.name or user.name
        else:
            user = User(
                tenant_id=tenant.id,
                name=identity.name,
                email=identity.email,
                role=default_role,
                google_oauth_subject=identity.subject,
            )
            session.add(user)
            await session.flush()

    if identity.refresh_token:
        await _store_refresh_token(
            session,
            tenant_id=user.tenant_id,
            refresh_token=identity.refresh_token,
            scopes=identity.granted_scopes,
        )

    await session.commit()
    return user


async def _store_refresh_token(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    refresh_token: str,
    scopes: list[str],
) -> None:
    encrypted = get_cipher().encrypt(refresh_token)
    credential = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant_id,
                IntegrationCredential.provider == GOOGLE_PROVIDER,
            )
        )
    ).scalar_one_or_none()
    if credential is None:
        session.add(
            IntegrationCredential(
                tenant_id=tenant_id,
                provider=GOOGLE_PROVIDER,
                encrypted_secret_reference=encrypted,
                scopes=scopes,
                status="active",
                last_verified_at=utcnow(),
            )
        )
    else:
        credential.encrypted_secret_reference = encrypted
        credential.scopes = scopes
        credential.status = "active"
        credential.last_verified_at = utcnow()
