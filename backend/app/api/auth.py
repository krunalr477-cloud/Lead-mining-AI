"""Auth endpoints: Google OAuth, session cookie, /me, dev login."""

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.constants import (
    DEMO_ADMIN_EMAIL,
    DEMO_TENANT_ID,
    DEMO_TENANT_NAME,
    DEMO_USER_ID,
    Role,
)
from app.deps import CurrentUser, SessionDep
from app.models import Tenant, User
from app.schemas.auth import MeResponse, TenantOut, UserOut, provider_modes
from app.security.auth import (
    SESSION_COOKIE_NAME,
    TOKEN_TTL,
    build_authorization_url,
    exchange_code,
    issue_token,
    upsert_google_user,
)

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(TOKEN_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        path="/",
    )


def _me_response(user: User, tenant: Tenant) -> MeResponse:
    settings = get_settings()
    return MeResponse(
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant),
        demo_mode=settings.demo_mode,
        providers=provider_modes(settings),
    )


@router.post("/auth/google/start")
async def google_start() -> dict[str, str]:
    """Begin the Google OAuth flow. 503 when OAuth is not configured."""
    return {"authorization_url": build_authorization_url()}


@router.get("/auth/google/callback", include_in_schema=False)
async def google_callback_browser(code: str, session: SessionDep) -> RedirectResponse:
    """Browser leg of the OAuth flow: set the session cookie and go to the app."""
    settings = get_settings()
    identity = await run_in_threadpool(exchange_code, code)
    user = await upsert_google_user(session, identity)
    response = RedirectResponse(
        f"{settings.frontend_url.rstrip('/')}/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    _set_session_cookie(response, issue_token(user))
    return response


class GoogleCallbackBody(BaseModel):
    code: str


@router.post("/auth/google/callback")
async def google_callback_api(body: GoogleCallbackBody, session: SessionDep) -> dict[str, str]:
    """API leg of the OAuth flow: exchange the code for a bearer token."""
    identity = await run_in_threadpool(exchange_code, body.code)
    user = await upsert_google_user(session, identity)
    return {"token": issue_token(user)}


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me")
async def me(user: CurrentUser, session: SessionDep) -> MeResponse:
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:  # orphaned session (tenant deleted)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    return _me_response(user, tenant)


@router.post("/auth/dev-login")
async def dev_login(response: Response, session: SessionDep) -> MeResponse:
    """Development-only login: admin user in the "Demo Workspace" tenant."""
    settings = get_settings()
    if settings.environment != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Upsert by the canonical demo IDs (shared with the demo seed) so dev-login
    # and `make seed` always converge on ONE tenant/user — never a duplicate.
    tenant = await session.get(Tenant, DEMO_TENANT_ID)
    if tenant is None:
        tenant = Tenant(id=DEMO_TENANT_ID, name=DEMO_TENANT_NAME)
        session.add(tenant)
        await session.flush()

    user = await session.get(User, DEMO_USER_ID)
    if user is None:
        user = User(
            id=DEMO_USER_ID,
            tenant_id=tenant.id,
            name="Demo Admin",
            email=DEMO_ADMIN_EMAIL,
            role=Role.ADMIN,
        )
        session.add(user)
        await session.flush()
    await session.commit()

    _set_session_cookie(response, issue_token(user))
    return _me_response(user, tenant)
