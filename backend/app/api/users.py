"""Tenant user management. All endpoints are admin-only via RBAC ("*")."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.deps import SessionDep, require
from app.models import User
from app.schemas.auth import UserInvite, UserOut, UserPatch

router = APIRouter(prefix="/users", tags=["users"])

# PERMISSIONS grants "users:*" to nobody explicitly, so only admin ("*") passes.
ReadActor = Annotated[User, Depends(require("users:read"))]
WriteActor = Annotated[User, Depends(require("users:write"))]


@router.get("", response_model=list[UserOut])
async def list_users(actor: ReadActor, session: SessionDep) -> list[User]:
    result = await session.execute(
        select(User).where(User.tenant_id == actor.tenant_id).order_by(User.created_at)
    )
    return list(result.scalars())


@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_user(body: UserInvite, actor: WriteActor, session: SessionDep) -> User:
    """Create the user row directly; no invitation email is sent."""
    email = body.email.lower()
    existing = (
        await session.execute(
            select(User).where(User.tenant_id == actor.tenant_id, User.email == email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists in this workspace",
        )
    user = User(tenant_id=actor.tenant_id, name=body.name, email=email, role=body.role)
    session.add(user)
    await session.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: uuid.UUID, body: UserPatch, actor: WriteActor, session: SessionDep
) -> User:
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    await session.commit()
    return user
