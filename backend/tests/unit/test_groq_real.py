"""Real GroqScorer unit tests — respx-mocked, no live network / no DB.

Covers: batch request shape (endpoint, model, JSON mode, temperature 0), JSON
parse -> (email, score, reason) tuples in input order, token usage recorded, a
429 falling back to the heuristic per-email WITHOUT raising, and a malformed body
also falling back cleanly.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters.llm.groq import _COMPLETIONS_URL, GroqScorer
from app.config import get_settings
from tests.unit._fakes import FakeContext


@pytest.fixture(autouse=True)
def _groq_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _completion(results: list[dict], total_tokens: int = 120) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps({"results": results})}}],
        "usage": {"total_tokens": total_tokens},
    }


@pytest.mark.asyncio
@respx.mock
async def test_batch_request_shape_and_parse():
    emails = ["ada.lovelace@analyticalengines.com", "asdfasdf@spam.io", "test123@throwaway.net"]
    body = _completion(
        [
            {"email": emails[0], "score": 0.95, "reason": "real personal name"},
            {"email": emails[1], "score": 0.02, "reason": "keyboard mash"},
            {"email": emails[2], "score": 0.05, "reason": "test pattern"},
        ]
    )
    route = respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
    ctx = FakeContext()

    out = await GroqScorer().score(emails, ctx)

    assert route.called
    req = json.loads(route.calls.last.request.content)
    assert req["model"] == "llama-3.1-8b-instant"
    assert req["temperature"] == 0
    assert req["response_format"] == {"type": "json_object"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer groq-test-key"

    # Tuples returned in input order with parsed scores/reasons.
    assert [e for e, _, _ in out] == emails
    assert out[0][1] == 0.95 and "personal" in out[0][2]
    assert out[1][1] == 0.02
    assert out[2][1] == 0.05

    # Token usage recorded.
    tok = [u for u in ctx.usages if u["endpoint"] == "chat.completions"]
    assert tok and tok[0]["request_count"] == 120


@pytest.mark.asyncio
@respx.mock
async def test_batches_over_20():
    emails = [f"user{i}@example.com" for i in range(45)]

    def handler(request):
        payload = json.loads(request.content)
        sent = payload["messages"][1]["content"].splitlines()[1:]
        results = [{"email": e, "score": 0.8, "reason": "ok"} for e in sent]
        return httpx.Response(200, json=_completion(results, total_tokens=10))

    route = respx.post(_COMPLETIONS_URL).mock(side_effect=handler)
    out = await GroqScorer().score(emails, FakeContext())

    assert route.call_count == 3  # 20 + 20 + 5
    assert [e for e, _, _ in out] == emails


@pytest.mark.asyncio
@respx.mock
async def test_429_falls_back_to_heuristic_without_raising():
    emails = ["real.person@company.com", "ab12@x.io"]
    respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(429, json={"error": "rate"}))
    ctx = FakeContext()

    out = await GroqScorer().score(emails, ctx)  # must NOT raise

    assert [e for e, _, _ in out] == emails
    assert all(0.0 <= s <= 1.0 for _, s, _ in out)
    assert all("fallback_heuristic" in reason for _, _, reason in out)


@pytest.mark.asyncio
@respx.mock
async def test_malformed_body_falls_back():
    emails = ["x@y.com"]
    respx.post(_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    )
    out = await GroqScorer().score(emails, FakeContext())
    assert out[0][0] == "x@y.com"
    assert "fallback_heuristic" in out[0][2]


@pytest.mark.asyncio
@respx.mock
async def test_missing_row_is_heuristic_filled():
    emails = ["a@b.com", "c@d.com"]
    # Model only returns a score for the first email.
    body = _completion([{"email": "a@b.com", "score": 0.7, "reason": "ok"}])
    respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
    out = await GroqScorer().score(emails, FakeContext())
    assert out[0][1] == 0.7 and "fallback_heuristic" not in out[0][2]
    assert "fallback_heuristic" in out[1][2]  # second heuristic-filled
