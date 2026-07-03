"""Integration: tenant credential store + probe against live Postgres (spec §17).

Exercises :mod:`app.services.credentials` end to end — store an encrypted
provider key, resolve it (stored-first), probe it (mock under DEMO_MODE), and
delete it — asserting the plaintext secret is never persisted in the clear and
the resolved mask is only ``****last4``.

These drive the async service through a single, self-contained event loop per
test (``asyncio.run``) over a ``NullPool`` engine that is disposed at the end,
so no asyncpg connection outlives its loop (the rest of the suite is sync-DB).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models import IntegrationCredential, Tenant
from app.services.credentials import (
    PROVIDER_SPECS,
    CredentialValidationError,
    delete_credential,
    probe_provider,
    resolve_secret,
    store_credential,
    stored_mask,
    validate_input,
)

Scenario = Callable[[async_sessionmaker[AsyncSession]], Awaitable[None]]


def _run(scenario: Scenario) -> None:
    """Run an async scenario on a fresh loop + NullPool engine, then dispose."""

    async def _main() -> None:
        engine = create_async_engine(get_settings().async_database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            await scenario(factory)
        finally:
            await engine.dispose()

    asyncio.run(_main())


async def _make_tenant(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    tid = uuid.uuid4()
    async with factory() as session:
        session.add(Tenant(id=tid, name=f"cred-test-{tid.hex[:8]}"))
        await session.commit()
    return tid


async def _drop_tenant(factory: async_sessionmaker[AsyncSession], tid: uuid.UUID) -> None:
    async with factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == tid))
        await session.commit()


async def _load(
    session: AsyncSession, tid: uuid.UUID, provider: str
) -> IntegrationCredential | None:
    return (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tid,
                IntegrationCredential.provider == provider,
            )
        )
    ).scalar_one_or_none()


def test_store_then_resolve_stored_first() -> None:
    secret = "gsk-live-key-tail5566"

    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        tid = await _make_tenant(factory)
        try:
            async with factory() as session:
                cleaned = validate_input(PROVIDER_SPECS["groq"], {"api_key": secret})
                cred = await store_credential(
                    session, tenant_id=tid, provider="groq", fields=cleaned
                )
                # Plaintext must never be persisted in the clear.
                assert secret not in cred.encrypted_secret_reference
                assert stored_mask(cred) == "****5566"

                resolved = await resolve_secret(session, tenant_id=tid, provider="groq")
                assert resolved.source == "stored"
                assert resolved.secret == secret
        finally:
            await _drop_tenant(factory, tid)

    _run(scenario)


def test_delete_is_idempotent() -> None:
    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        tid = await _make_tenant(factory)
        try:
            async with factory() as session:
                cleaned = validate_input(PROVIDER_SPECS["serp"], {"api_key": "serp-abcd"})
                await store_credential(session, tenant_id=tid, provider="serp", fields=cleaned)
                assert await delete_credential(session, tenant_id=tid, provider="serp") is True
                assert await delete_credential(session, tenant_id=tid, provider="serp") is False
                assert await _load(session, tid, "serp") is None
        finally:
            await _drop_tenant(factory, tid)

    _run(scenario)


def test_oauth_requires_both_fields() -> None:
    spec = PROVIDER_SPECS["google_oauth"]
    with pytest.raises(CredentialValidationError):
        validate_input(spec, {"client_id": "only-id"})  # missing client_secret


def test_probe_not_configured() -> None:
    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        tid = await _make_tenant(factory)
        try:
            async with factory() as session:
                result = await probe_provider(session, tenant_id=tid, provider="groq")
            assert result.ok is False
            assert result.status == "not_configured"
        finally:
            await _drop_tenant(factory, tid)

    _run(scenario)


def test_probe_stored_key_reports_mock_under_demo() -> None:
    # DEMO_MODE is on in the test env: a stored key probes as mock, ok=True, and
    # the probe message must NOT contain the secret.
    secret = "gsk-secret-tail0001"

    async def scenario(factory: async_sessionmaker[AsyncSession]) -> None:
        tid = await _make_tenant(factory)
        try:
            async with factory() as session:
                cleaned = validate_input(PROVIDER_SPECS["groq"], {"api_key": secret})
                await store_credential(session, tenant_id=tid, provider="groq", fields=cleaned)
                result = await probe_provider(session, tenant_id=tid, provider="groq")
            assert result.ok is True
            assert result.status == "mock"
            assert secret not in (result.message or "")
        finally:
            await _drop_tenant(factory, tid)

    _run(scenario)
