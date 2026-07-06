"""JWT session tokens plus Google and Microsoft (Entra ID) OAuth sign-in.

Session tokens are HS256 JWTs (7-day expiry) carried in the ``lm_session``
httpOnly cookie or an ``Authorization: Bearer`` header.

Google sign-in uses the google-auth-oauthlib ``Flow`` with offline access so we
always receive a refresh token. Microsoft sign-in mirrors it against the
Microsoft identity platform (login.microsoftonline.com) v2.0 endpoints. Both
store the provider refresh token Fernet-encrypted per tenant in
IntegrationCredential, and both funnel through the shared
:func:`_upsert_oauth_user` for tenant/user provisioning.

CSRF: the authorization URL carries a signed, short-lived ``state`` JWT. The API
layer also stores that same value in a cookie and, on callback, requires the
query ``state`` to both verify (signature + expiry) and match the cookie —
defeating login CSRF and stray/replayed callbacks.
"""

import base64
import binascii
import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
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
OAUTH_STATE_COOKIE_NAME = "lm_oauth_state"
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=7)
STATE_TTL = timedelta(minutes=10)

# Full URLs (not the "email"/"profile" aliases) so the scopes Google echoes
# back match what we requested and oauthlib does not flag a scope change. We
# request Sheets + Gmail up front so a signed-in operator can drive the export
# and campaign features without a second consent round-trip.
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

GOOGLE_PROVIDER = "google"
MICROSOFT_PROVIDER = "microsoft"

# Microsoft identity platform (v2.0) — tenant is substituted at call time.
_MS_AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_MS_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


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


# ----------------------------------------------------------------- CSRF state


def issue_oauth_state(provider: str) -> str:
    """Short-lived signed state token binding the callback to this provider.

    Carries a random nonce (opacity) and the provider (so a Google callback
    can't consume a Microsoft state and vice-versa). Verified on callback.
    """
    settings = get_settings()
    now = utcnow()
    payload = {
        "nonce": secrets.token_urlsafe(16),
        "provider": provider,
        "iat": now,
        "exp": now + STATE_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def verify_oauth_state(state: str, cookie_state: str | None, provider: str) -> None:
    """Validate an OAuth callback ``state`` against the signed value + cookie.

    Rejects (400) when: state/cookie missing, they differ, the signature or
    expiry is invalid, or the embedded provider does not match. This is the
    login-CSRF guard — an attacker cannot forge a state we will accept.
    """
    settings = get_settings()
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state mismatch — restart sign-in.",
        )
    try:
        claims = jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state expired or invalid — restart sign-in.",
        ) from exc
    if claims.get("provider") != provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state provider mismatch — restart sign-in.",
        )


# ------------------------------------------------------------------ shared upsert


@dataclass(frozen=True, slots=True)
class OAuthIdentity:
    """Verified identity extracted from an OAuth code exchange (any provider)."""

    provider: str
    subject: str
    email: str
    name: str
    workspace_domain: str | None  # a hosted-domain hint; None for consumer accounts
    refresh_token: str | None
    granted_scopes: list[str] = field(default_factory=list)


# Backwards-compatible alias — some call sites / tests import GoogleIdentity.
GoogleIdentity = OAuthIdentity


async def _upsert_oauth_user(
    session: AsyncSession,
    *,
    provider: str,
    subject: str,
    email: str,
    name: str,
    refresh_token: str | None = None,
    workspace_domain: str | None = None,
    granted_scopes: list[str] | None = None,
) -> User:
    """Provision (or refresh) the tenant + user for a verified OAuth identity.

    Resolution order:
      1. Google identities match an existing user by ``google_oauth_subject``.
      2. Otherwise dedupe by email: the first user of a domain creates a new
         tenant and becomes its ``admin``; later users on the same domain join
         as ``sales_executive`` (or claim a pre-invited row matched by email).
    The provider refresh token, when present, is stored Fernet-encrypted per
    tenant in IntegrationCredential(provider=<provider>).
    """
    email = (email or "").lower()
    domain = workspace_domain or (email.split("@", 1)[1] if "@" in email else None)
    granted_scopes = granted_scopes or []

    user: User | None = None
    if provider == GOOGLE_PROVIDER:
        user = (
            await session.execute(select(User).where(User.google_oauth_subject == subject))
        ).scalar_one_or_none()

    if user is not None:
        user.name = name or user.name
        user.email = email or user.email
    else:
        tenant: Tenant | None = None
        if domain:
            tenant = (
                await session.execute(
                    select(Tenant).where(Tenant.google_workspace_domain == domain)
                )
            ).scalar_one_or_none()

        if tenant is None:
            tenant = Tenant(
                name=domain or "My Workspace",
                google_workspace_domain=domain,
            )
            session.add(tenant)
            await session.flush()
            default_role = Role.ADMIN  # first user of a tenant is its admin
        else:
            default_role = Role.SALES_EXECUTIVE

        # A user may have been invited by email before their first login, or may
        # already exist from a prior sign-in with a different provider.
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.email == email)
            )
        ).scalar_one_or_none()
        if user is not None:
            user.name = name or user.name
            if provider == GOOGLE_PROVIDER and not user.google_oauth_subject:
                user.google_oauth_subject = subject
        else:
            user = User(
                tenant_id=tenant.id,
                name=name or (email.split("@", 1)[0] if email else "User"),
                email=email,
                role=default_role,
                google_oauth_subject=subject if provider == GOOGLE_PROVIDER else None,
            )
            session.add(user)
            await session.flush()

    if refresh_token:
        await _store_refresh_token(
            session,
            tenant_id=user.tenant_id,
            provider=provider,
            refresh_token=refresh_token,
            scopes=granted_scopes,
        )

    await session.commit()
    return user


async def _store_refresh_token(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    refresh_token: str,
    scopes: list[str],
) -> None:
    encrypted = get_cipher().encrypt(refresh_token)
    credential = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant_id,
                IntegrationCredential.provider == provider,
            )
        )
    ).scalar_one_or_none()
    if credential is None:
        session.add(
            IntegrationCredential(
                tenant_id=tenant_id,
                provider=provider,
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


# ------------------------------------------------------------------- Google OAuth


def _resolve_google_client() -> tuple[str, str] | None:
    """Effective (client_id, client_secret) for the OAuth flow.

    Env values win; when they are empty we fall back to a stored ``google_oauth``
    client credential (set from Settings -> Integrations by a bootstrap admin) so
    an operator can wire sign-in entirely from the UI without a redeploy. Returns
    None when neither source yields both fields.
    """
    settings = get_settings()
    if settings.google_client_id and settings.google_client_secret:
        return settings.google_client_id, settings.google_client_secret
    stored = _stored_google_client()
    if stored is not None:
        return stored
    return None


def _stored_google_client() -> tuple[str, str] | None:
    """Read a stored google_oauth client credential via a short sync session.

    The login flow is unauthenticated (no tenant yet) and the OAuth *client* is
    an app-level secret, so we accept any active ``google_oauth`` row — an admin
    configures it once for the deployment. Never raises: any error resolves to
    None so the caller falls through to the actionable 503.
    """
    try:
        from app.db import sync_session_factory
        from app.models import IntegrationCredential
        from app.security.crypto import decrypt_credential

        with sync_session_factory() as session:
            row = (
                session.execute(
                    select(IntegrationCredential)
                    .where(
                        IntegrationCredential.provider == "google_oauth",
                        IntegrationCredential.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None or not row.encrypted_secret_reference:
                return None
            fields = decrypt_credential(row.encrypted_secret_reference)
            client_id = fields.get("client_id")
            client_secret = fields.get("client_secret")
            if client_id and client_secret:
                return client_id, client_secret
    except Exception:
        return None
    return None


def _build_flow(state: str | None = None) -> Flow:
    settings = get_settings()
    resolved = _resolve_google_client()
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google sign-in isn't configured. Add a Google OAuth Client ID and "
                "Secret under Settings -> Integrations (or set GOOGLE_CLIENT_ID / "
                "GOOGLE_CLIENT_SECRET in .env), then retry. Use Dev Login meanwhile."
            ),
        )
    client_id, client_secret = resolved
    # Google reorders/expands granted scopes; don't let oauthlib treat that as
    # an error. In development the redirect URI is plain http://localhost.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    if settings.environment == "development":
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=GOOGLE_OAUTH_SCOPES,
        state=state,
    )
    # Must EXACTLY equal the URI registered in the Google Cloud console and the
    # one we later exchange against, or Google rejects the callback.
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def build_authorization_url(state: str | None = None) -> str:
    """Google consent-screen URL requesting offline access (refresh token)."""
    flow = _build_flow(state=state)
    authorization_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return authorization_url


def exchange_code(code: str) -> OAuthIdentity:
    """Blocking Google code exchange + id_token verification.

    Call from async routes via ``run_in_threadpool``.
    """
    resolved = _resolve_google_client()
    if resolved is None:  # pragma: no cover - _build_flow raises first
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth not configured",
        )
    client_id, _client_secret = resolved
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
            client_id,
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
    return OAuthIdentity(
        provider=GOOGLE_PROVIDER,
        subject=claims["sub"],
        email=email,
        name=claims.get("name") or email.split("@")[0],
        workspace_domain=claims.get("hd"),
        refresh_token=credentials.refresh_token,
        granted_scopes=list(credentials.scopes or []),
    )


async def upsert_google_user(session: AsyncSession, identity: OAuthIdentity) -> User:
    """Tenant/User upsert for a verified Google identity (thin shim)."""
    return await _upsert_oauth_user(
        session,
        provider=GOOGLE_PROVIDER,
        subject=identity.subject,
        email=identity.email,
        name=identity.name,
        refresh_token=identity.refresh_token,
        workspace_domain=identity.workspace_domain,
        granted_scopes=identity.granted_scopes,
    )


# --------------------------------------------------------------- Microsoft OAuth


def _resolve_ms_client() -> tuple[str, str] | None:
    """Effective (client_id, client_secret) for Microsoft sign-in, or None.

    Env values win; when empty, fall back to a stored ``microsoft_oauth`` client
    credential configured from Settings -> Integrations, matching the Google
    resolution model so an operator can wire sign-in without a redeploy.
    """
    settings = get_settings()
    if settings.microsoft_client_id and settings.microsoft_client_secret:
        return settings.microsoft_client_id, settings.microsoft_client_secret
    stored = _stored_ms_client()
    if stored is not None:
        return stored
    return None


def _stored_ms_client() -> tuple[str, str] | None:
    """Read a stored microsoft_oauth client credential via a short sync session."""
    try:
        from app.db import sync_session_factory
        from app.models import IntegrationCredential
        from app.security.crypto import decrypt_credential

        with sync_session_factory() as session:
            row = (
                session.execute(
                    select(IntegrationCredential)
                    .where(
                        IntegrationCredential.provider == "microsoft_oauth",
                        IntegrationCredential.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None or not row.encrypted_secret_reference:
                return None
            fields = decrypt_credential(row.encrypted_secret_reference)
            client_id = fields.get("client_id")
            client_secret = fields.get("client_secret")
            if client_id and client_secret:
                return client_id, client_secret
    except Exception:
        return None
    return None


def _require_ms_client() -> tuple[str, str]:
    resolved = _resolve_ms_client()
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Microsoft sign-in not configured — add MICROSOFT_CLIENT_ID / "
                "MICROSOFT_CLIENT_SECRET in Settings -> Integrations or .env, then "
                "retry. Use Dev Login meanwhile."
            ),
        )
    return resolved


def build_ms_authorization_url(state: str | None = None) -> str:
    """Microsoft identity platform consent URL (authorization-code + PKCE-free).

    Uses the configured tenant ("common" by default) and requests
    ``offline_access`` so the token endpoint returns a refresh token.
    """
    settings = get_settings()
    client_id, _secret = _require_ms_client()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": settings.microsoft_redirect_uri,
        "response_mode": "query",
        "scope": settings.microsoft_scopes,
        "prompt": "select_account",
    }
    if state:
        params["state"] = state
    base = _MS_AUTHORIZE_URL.format(tenant=settings.microsoft_tenant)
    return str(httpx.URL(base, params=params))


def _decode_jwt_claims(token: str) -> dict:
    """Decode a JWT payload segment WITHOUT signature verification.

    The id_token here arrives directly from Microsoft's token endpoint over a
    server-to-server TLS call authenticated with our client secret, so its
    integrity is already established by the channel — we only need to read
    claims (email/name/oid). Never trust an id_token decoded this way if it did
    not come straight from a trusted token exchange.
    """
    try:
        _header, payload, *_ = token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft id_token could not be decoded",
        ) from exc


async def exchange_ms_code(code: str) -> OAuthIdentity:
    """Exchange a Microsoft authorization code for tokens and read the identity.

    Reads email from ``email`` or ``preferred_username``, name from ``name``,
    and the stable subject from ``oid`` (falling back to ``sub``).
    """
    settings = get_settings()
    client_id, client_secret = _require_ms_client()
    token_url = _MS_TOKEN_URL.format(tenant=settings.microsoft_tenant)
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.microsoft_redirect_uri,
        "scope": settings.microsoft_scopes,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Microsoft token endpoint",
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft OAuth code exchange failed",
        )

    tokens = resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft response had no id_token",
        )
    claims = _decode_jwt_claims(id_token)

    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft account has no usable email claim",
        )
    subject = claims.get("oid") or claims.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft id_token has no subject (oid/sub) claim",
        )

    scope = tokens.get("scope", "")
    return OAuthIdentity(
        provider=MICROSOFT_PROVIDER,
        subject=str(subject),
        email=email,
        name=claims.get("name") or email.split("@")[0],
        # Entra id_tokens don't carry Google's ``hd``; the domain is derived
        # from the email in the shared upsert.
        workspace_domain=None,
        refresh_token=tokens.get("refresh_token"),
        granted_scopes=scope.split() if scope else [],
    )


async def upsert_microsoft_user(session: AsyncSession, identity: OAuthIdentity) -> User:
    """Tenant/User upsert for a verified Microsoft identity (thin shim)."""
    return await _upsert_oauth_user(
        session,
        provider=MICROSOFT_PROVIDER,
        subject=identity.subject,
        email=identity.email,
        name=identity.name,
        refresh_token=identity.refresh_token,
        workspace_domain=identity.workspace_domain,
        granted_scopes=identity.granted_scopes,
    )
