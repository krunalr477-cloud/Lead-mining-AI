"""FastAPI dependencies: DB session, current user, tenant scoping, RBAC."""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import Role
from app.db import async_session_factory
from app.models import User
from app.security.auth import SESSION_COOKIE_NAME, verify_token
from app.security.rbac import has_permission


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_async_session)]


def _extract_token(request: Request) -> str | None:
    """Session JWT from the lm_session cookie or an Authorization: Bearer header."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token
    authorization = request.headers.get("Authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return credentials.strip()
    return None


async def get_current_user(request: Request, session: SessionDep) -> User:
    token = _extract_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify_token(token)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_tenant_id(user: CurrentUser) -> uuid.UUID:
    return user.tenant_id


TenantId = Annotated[uuid.UUID, Depends(get_tenant_id)]


def require(permission: str) -> Callable[..., Coroutine[None, None, User]]:
    """Dependency factory: 403 unless the current user's role grants `permission`.

    Purely role-based — ownership-scoped permissions such as
    "contacts:write_own" are enforced by the routers themselves.
    """

    async def checker(user: CurrentUser) -> User:
        try:
            role = Role(user.role)
        except ValueError:
            role = None
        if role is None or not has_permission(role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return user

    return checker
