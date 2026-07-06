"""Google + Microsoft (Entra ID) OAuth sign-in — offline unit tests.

No real Google/Microsoft network is touched: the Google flow is monkeypatched at
the resolve-client + Flow boundary, and the Microsoft token exchange is respx-
mocked with a crafted id_token. The shared ``_upsert_oauth_user`` is exercised
against a live Postgres via a NullPool engine on a self-contained event loop
(matching the credential integration tests), with the created tenant torn down.

Covers:
  * /auth/{google,microsoft}/start 503 with the actionable detail when unset.
  * start returns an authorization_url at the right host with the right
    client_id / redirect_uri / scope / signed state.
  * exchange_ms_code parses a fake token response + id_token claims.
  * _upsert_oauth_user: first same-domain user -> new tenant + admin, second ->
    sales_executive; dedupe by email.
  * OAuth state mismatch / tampering is rejected.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid

import httpx
import jwt
import pytest
import respx
from fastapi import HTTPException, Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.auth import google_start, microsoft_start
from app.config import get_settings
from app.constants import Role
from app.models import Tenant
from app.security import auth as auth_mod
from app.security.auth import (
    _MS_TOKEN_URL,
    GOOGLE_PROVIDER,
    MICROSOFT_PROVIDER,
    OAUTH_STATE_COOKIE_NAME,
    _upsert_oauth_user,
    build_ms_authorization_url,
    exchange_ms_code,
    issue_oauth_state,
    verify_oauth_state,
)

# --------------------------------------------------------------------------- #
# DB harness (mirrors tests/integration/test_integrations_credentials.py)
# --------------------------------------------------------------------------- #


def _run(scenario) -> None:
    async def _main() -> None:
        engine = create_async_engine(get_settings().async_database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            await scenario(factory)
        finally:
            await engine.dispose()

    asyncio.run(_main())


async def _drop_domain(factory, domain: str) -> None:
    async with factory() as session:
        await session.execute(delete(Tenant).where(Tenant.google_workspace_domain == domain))
        await session.commit()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _fake_id_token(claims: dict) -> str:
    """A JWT-shaped string whose payload segment decodes to ``claims``.

    Signature is irrelevant: exchange_ms_code decodes claims WITHOUT verifying
    the signature (the token comes over the trusted server-to-server exchange).
    """

    def _seg(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{_seg({'alg': 'RS256', 'typ': 'JWT'})}.{_seg(claims)}.sig"


@pytest.fixture
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# start-endpoint: 503 when unconfigured
# --------------------------------------------------------------------------- #


def test_google_start_503_when_unconfigured(monkeypatch, _clear_settings):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    get_settings.cache_clear()
    # No stored fallback either.
    monkeypatch.setattr(auth_mod, "_stored_google_client", lambda: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(google_start(Response()))
    assert exc.value.status_code == 503
    assert "Google sign-in isn't configured" in exc.value.detail


def test_microsoft_start_503_when_unconfigured(monkeypatch, _clear_settings):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "")
    get_settings.cache_clear()
    monkeypatch.setattr(auth_mod, "_stored_ms_client", lambda: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(microsoft_start(Response()))
    assert exc.value.status_code == 503
    assert "Microsoft sign-in not configured" in exc.value.detail
    assert "MICROSOFT_CLIENT_ID" in exc.value.detail


# --------------------------------------------------------------------------- #
# start-endpoint: real authorization_url + signed state when configured
# --------------------------------------------------------------------------- #


def test_google_start_returns_url_and_sets_state(monkeypatch, _clear_settings):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid-123.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    get_settings.cache_clear()

    response = Response()
    data = asyncio.run(google_start(response))
    url = httpx.URL(data["authorization_url"])
    assert url.host == "accounts.google.com"
    params = dict(url.params)
    assert params["client_id"] == "gid-123.apps.googleusercontent.com"
    assert params["redirect_uri"] == "http://localhost:8000/api/v1/auth/google/callback"
    assert params["access_type"] == "offline"
    assert "openid" in params["scope"]
    assert "spreadsheets" in params["scope"]  # sheets requested up-front
    assert "gmail.send" in params["scope"]  # gmail requested up-front
    # The state travels in the URL AND is set as an httpOnly cookie (CSRF).
    state = params["state"]
    assert state
    set_cookie = response.headers.get("set-cookie", "")
    assert OAUTH_STATE_COOKIE_NAME in set_cookie
    assert state in set_cookie
    # State is our own signed JWT bound to the google provider.
    claims = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    assert claims["provider"] == GOOGLE_PROVIDER


def test_microsoft_start_returns_url_and_sets_state(monkeypatch, _clear_settings):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "ms-client-abc")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_TENANT", "common")
    monkeypatch.setenv(
        "MICROSOFT_REDIRECT_URI", "http://localhost:8000/api/v1/auth/microsoft/callback"
    )
    get_settings.cache_clear()

    response = Response()
    data = asyncio.run(microsoft_start(response))
    url = httpx.URL(data["authorization_url"])
    assert url.host == "login.microsoftonline.com"
    assert url.path == "/common/oauth2/v2.0/authorize"
    params = dict(url.params)
    assert params["client_id"] == "ms-client-abc"
    assert params["response_type"] == "code"
    assert params["redirect_uri"] == "http://localhost:8000/api/v1/auth/microsoft/callback"
    assert "offline_access" in params["scope"]
    assert "User.Read" in params["scope"]
    state = params["state"]
    assert state
    set_cookie = response.headers.get("set-cookie", "")
    assert OAUTH_STATE_COOKIE_NAME in set_cookie
    claims = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    assert claims["provider"] == MICROSOFT_PROVIDER


def test_build_ms_authorization_url_respects_tenant(monkeypatch, _clear_settings):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "ms-client-abc")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_TENANT", "contoso.onmicrosoft.com")
    get_settings.cache_clear()

    url = httpx.URL(build_ms_authorization_url(state="s"))
    assert url.path == "/contoso.onmicrosoft.com/oauth2/v2.0/authorize"


# --------------------------------------------------------------------------- #
# Microsoft code exchange — respx-mocked token endpoint + crafted id_token
# --------------------------------------------------------------------------- #


@respx.mock
def test_exchange_ms_code_parses_claims(monkeypatch, _clear_settings):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "ms-client-abc")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_TENANT", "common")
    get_settings.cache_clear()

    id_token = _fake_id_token(
        {
            "oid": "ms-oid-777",
            "name": "Grace Hopper",
            "preferred_username": "grace@contoso.com",
            "email": "grace@contoso.com",
        }
    )
    token_url = _MS_TOKEN_URL.format(tenant="common")
    route = respx.post(token_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt-abc",
                "id_token": id_token,
                "scope": "openid email profile offline_access User.Read",
            },
        )
    )

    identity = asyncio.run(exchange_ms_code("authcode"))

    assert route.called
    sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "authcode"
    assert sent["client_id"] == "ms-client-abc"

    assert identity.provider == MICROSOFT_PROVIDER
    assert identity.subject == "ms-oid-777"
    assert identity.email == "grace@contoso.com"
    assert identity.name == "Grace Hopper"
    assert identity.refresh_token == "rt-abc"
    assert "User.Read" in identity.granted_scopes


@respx.mock
def test_exchange_ms_code_falls_back_to_preferred_username(monkeypatch, _clear_settings):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "ms-client-abc")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_TENANT", "common")
    get_settings.cache_clear()

    id_token = _fake_id_token({"sub": "sub-fallback", "preferred_username": "bob@fabrikam.com"})
    respx.post(_MS_TOKEN_URL.format(tenant="common")).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )
    identity = asyncio.run(exchange_ms_code("c"))
    assert identity.email == "bob@fabrikam.com"
    assert identity.subject == "sub-fallback"
    assert identity.refresh_token is None  # none returned by the endpoint


@respx.mock
def test_exchange_ms_code_400_on_token_error(monkeypatch, _clear_settings):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "ms-client-abc")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_TENANT", "common")
    get_settings.cache_clear()
    respx.post(_MS_TOKEN_URL.format(tenant="common")).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(exchange_ms_code("bad"))
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------- #
# CSRF state validation
# --------------------------------------------------------------------------- #


def test_verify_oauth_state_accepts_matching_signed_state(_clear_settings):
    get_settings.cache_clear()
    state = issue_oauth_state(GOOGLE_PROVIDER)
    # matching cookie + correct provider -> no raise
    verify_oauth_state(state, state, GOOGLE_PROVIDER)


def test_verify_oauth_state_rejects_mismatch(_clear_settings):
    get_settings.cache_clear()
    state = issue_oauth_state(GOOGLE_PROVIDER)
    other = issue_oauth_state(GOOGLE_PROVIDER)
    with pytest.raises(HTTPException) as exc:
        verify_oauth_state(state, other, GOOGLE_PROVIDER)
    assert exc.value.status_code == 400


def test_verify_oauth_state_rejects_missing_cookie(_clear_settings):
    get_settings.cache_clear()
    state = issue_oauth_state(GOOGLE_PROVIDER)
    with pytest.raises(HTTPException):
        verify_oauth_state(state, None, GOOGLE_PROVIDER)


def test_verify_oauth_state_rejects_wrong_provider(_clear_settings):
    get_settings.cache_clear()
    state = issue_oauth_state(GOOGLE_PROVIDER)
    with pytest.raises(HTTPException) as exc:
        verify_oauth_state(state, state, MICROSOFT_PROVIDER)
    assert exc.value.status_code == 400


def test_verify_oauth_state_rejects_tampered_signature(monkeypatch, _clear_settings):
    get_settings.cache_clear()
    forged = jwt.encode(
        {"provider": GOOGLE_PROVIDER, "exp": 9999999999, "nonce": "x"},
        "not-the-real-secret-but-long-enough-to-avoid-key-length-warning",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        verify_oauth_state(forged, forged, GOOGLE_PROVIDER)
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------- #
# _upsert_oauth_user — tenant/user provisioning + role assignment
# --------------------------------------------------------------------------- #


def test_upsert_first_user_admin_second_sales_executive(monkeypatch, _clear_settings):
    monkeypatch.setenv("DEMO_MODE", "true")  # ephemeral cipher key for refresh-token storage
    get_settings.cache_clear()
    domain = f"acme-{uuid.uuid4().hex[:8]}.example"
    email_a = f"founder@{domain}"
    email_b = f"rep@{domain}"

    async def scenario(factory):
        try:
            async with factory() as session:
                admin = await _upsert_oauth_user(
                    session,
                    provider=MICROSOFT_PROVIDER,
                    subject="oid-a",
                    email=email_a,
                    name="Founder",
                    refresh_token="rt-a",
                )
                assert admin.role == Role.ADMIN
                admin_tenant = admin.tenant_id

            async with factory() as session:
                rep = await _upsert_oauth_user(
                    session,
                    provider=MICROSOFT_PROVIDER,
                    subject="oid-b",
                    email=email_b,
                    name="Rep",
                )
                assert rep.role == Role.SALES_EXECUTIVE
                assert rep.tenant_id == admin_tenant  # same tenant (same domain)

            # Re-login of the admin dedupes by email — no duplicate row/tenant.
            async with factory() as session:
                again = await _upsert_oauth_user(
                    session,
                    provider=MICROSOFT_PROVIDER,
                    subject="oid-a",
                    email=email_a,
                    name="Founder Renamed",
                )
                assert again.tenant_id == admin_tenant
                assert again.role == Role.ADMIN
                assert again.name == "Founder Renamed"
        finally:
            await _drop_domain(factory, domain)

    _run(scenario)


def test_upsert_google_matches_on_subject(monkeypatch, _clear_settings):
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    domain = f"globex-{uuid.uuid4().hex[:8]}.example"
    email = f"eng@{domain}"

    async def scenario(factory):
        try:
            async with factory() as session:
                first = await _upsert_oauth_user(
                    session,
                    provider=GOOGLE_PROVIDER,
                    subject="gsub-1",
                    email=email,
                    name="Engineer",
                    refresh_token="rt-google",
                    workspace_domain=domain,
                )
                assert first.role == Role.ADMIN
                assert first.google_oauth_subject == "gsub-1"
                first_id = first.id

            # Same google subject but the email changed -> still the same user.
            async with factory() as session:
                again = await _upsert_oauth_user(
                    session,
                    provider=GOOGLE_PROVIDER,
                    subject="gsub-1",
                    email=f"eng.new@{domain}",
                    name="Engineer",
                    workspace_domain=domain,
                )
                assert again.id == first_id
                assert again.email == f"eng.new@{domain}"
        finally:
            await _drop_domain(factory, domain)

    _run(scenario)
