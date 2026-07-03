"""Real MillionVerifierAdapter unit tests — respx-mocked, no live network / no DB.

Covers: each provider ``result`` string -> the correct MillionVerifierStatus,
raw payload returned unchanged, one credit recorded, 30-day cache prevents a
second call, and 429 -> UNKNOWN (retry) without spending a credit.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.validation.millionverifier import _VERIFY_URL, MillionVerifierAdapter, map_result
from app.config import get_settings
from app.constants import MillionVerifierStatus
from tests.unit._fakes import FakeContext, FakeRedis


@pytest.fixture(autouse=True)
def _mv_key(monkeypatch):
    monkeypatch.setenv("MILLIONVERIFIER_API_KEY", "mv-test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "result_str,expected",
    [
        ("ok", MillionVerifierStatus.VALID),
        ("valid", MillionVerifierStatus.VALID),
        ("invalid", MillionVerifierStatus.INVALID),
        ("catch_all", MillionVerifierStatus.CATCH_ALL),
        ("unknown", MillionVerifierStatus.UNKNOWN),
        ("disposable", MillionVerifierStatus.INVALID),
        ("risky", MillionVerifierStatus.RISK),
        ("weird_new_value", MillionVerifierStatus.UNKNOWN),
    ],
)
def test_map_result(result_str, expected):
    assert map_result(result_str) is expected


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "result_str,expected",
    [
        ("ok", MillionVerifierStatus.VALID),
        ("invalid", MillionVerifierStatus.INVALID),
        ("catch_all", MillionVerifierStatus.CATCH_ALL),
        ("unknown", MillionVerifierStatus.UNKNOWN),
        ("disposable", MillionVerifierStatus.INVALID),
        ("risky", MillionVerifierStatus.RISK),
    ],
)
async def test_verify_maps_and_returns_raw(result_str, expected):
    body = {"email": "x@y.com", "result": result_str, "quality": "high", "credits": 100}
    respx.get(_VERIFY_URL).mock(return_value=httpx.Response(200, json=body))
    ctx = FakeContext()

    status, raw = await MillionVerifierAdapter().verify("x@y.com", ctx)

    assert status == expected.value
    assert raw == body  # raw provider payload stored unchanged
    credit = [u for u in ctx.usages if u["endpoint"] == "email.verify"]
    assert len(credit) == 1
    assert credit[0]["unit_cost"] == 0.0008


@pytest.mark.asyncio
@respx.mock
async def test_cache_prevents_second_call():
    body = {"email": "cached@y.com", "result": "ok"}
    route = respx.get(_VERIFY_URL).mock(return_value=httpx.Response(200, json=body))
    redis = FakeRedis()

    ctx1 = FakeContext(redis=redis)
    s1, _ = await MillionVerifierAdapter().verify("cached@y.com", ctx1)
    ctx2 = FakeContext(redis=redis)
    s2, raw2 = await MillionVerifierAdapter().verify("cached@y.com", ctx2)

    assert route.call_count == 1
    assert s1 == s2 == MillionVerifierStatus.VALID.value
    assert raw2 == body
    assert not any(u["endpoint"] == "email.verify" for u in ctx2.usages)


@pytest.mark.asyncio
@respx.mock
async def test_rate_limited_returns_unknown_no_credit():
    respx.get(_VERIFY_URL).mock(return_value=httpx.Response(429, json={"error": "rate"}))
    ctx = FakeContext()
    status, raw = await MillionVerifierAdapter().verify("throttled@y.com", ctx)
    assert status == MillionVerifierStatus.UNKNOWN.value
    assert raw["reason"] == "rate_limited"
    assert not any(u["endpoint"] == "email.verify" for u in ctx.usages)
