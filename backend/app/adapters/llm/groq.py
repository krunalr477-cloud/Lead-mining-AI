"""Real Groq LLM email-scorer adapter (spec §11 stage 5).

Scores each email's *local part* for how likely it is a real personal address vs
an obvious fake (``asdfasdf@``, ``test123@``, keyboard-mash / random strings). We
call Groq's OpenAI-compatible Chat Completions endpoint in JSON mode at
temperature 0 for determinism, batching up to 20 emails per request.

Endpoint: ``POST https://api.groq.com/openai/v1/chat/completions`` with
``Authorization: Bearer <key>``, ``model = settings.groq_model``,
``response_format = {"type": "json_object"}``. The model is asked to return
``{"results": [{"email", "score", "reason"}]}``.

Robustness (spec: "parse robustly"):
- Any parse failure, a 429/5xx, a short/missing/misaligned result set, or a bad
  score all fall back to the deterministic heuristic scorer *per email*, with the
  reason tagged ``fallback_heuristic`` so the source of a score is auditable.
- The fallback never raises, so a flaky LLM can't fail validation.
Token usage is recorded from the response ``usage`` block via ``ctx.record_usage``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.adapters._http import ProviderError, ProviderRateLimited, audited_request
from app.adapters.base import LLMScorerAdapter
from app.adapters.mock.providers import MockGroqScorerAdapter
from app.config import get_settings

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["GroqScorer"]

_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
_BATCH_SIZE = 20
_FALLBACK_TAG = "fallback_heuristic"
# Very rough Groq token pricing (USD/token) for cost estimation only.
_UNIT_COST_PER_TOKEN = 0.00000005

_SYSTEM_PROMPT = (
    "You are an email quality classifier. For each email address, judge how likely "
    "the LOCAL PART (before the @) belongs to a real person or role at a company, "
    "versus an obviously fake, test, or random string. Give a low score (near 0.0) "
    "to obvious fakes such as asdfasdf@, test123@, qwerty@, keyboard mashes, and "
    "random character strings. Give a high score (near 1.0) to plausible human "
    "names or normal business locals. Respond ONLY with a JSON object of the form "
    '{"results": [{"email": "<email>", "score": <float 0..1>, "reason": "<short>"}]} '
    "with one entry per input email, in the same order."
)


class GroqScorer(LLMScorerAdapter):
    """Live Groq scorer with per-email heuristic fallback. Key-gated at runtime."""

    provider = "groq"
    required_credentials = ["GROQ_API_KEY"]

    _fallback = MockGroqScorerAdapter()

    async def score(self, emails: list[str], ctx: SourceRunContext) -> list[tuple[str, float, str]]:
        if not emails:
            return []

        settings = get_settings()
        api_key = settings.groq_api_key
        if not api_key:  # resolver should prevent this; degrade to heuristic.
            return [self._fallback_one(e) for e in emails]

        results: list[tuple[str, float, str]] = []
        for start in range(0, len(emails), _BATCH_SIZE):
            batch = emails[start : start + _BATCH_SIZE]
            results.extend(await self._score_batch(batch, settings, api_key, ctx))
        return results

    async def _score_batch(
        self,
        batch: list[str],
        settings: Any,
        api_key: str,
        ctx: SourceRunContext,
    ) -> list[tuple[str, float, str]]:
        body = {
            "model": settings.groq_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Score these emails:\n" + "\n".join(batch),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        try:
            response = await audited_request(
                ctx,
                "POST",
                _COMPLETIONS_URL,
                audit_url="groq:chat.completions",
                headers=headers,
                json=body,
                records_found=len(batch),
            )
        except (ProviderRateLimited, ProviderError):
            # 429/5xx/4xx — fall back to the heuristic for the whole batch.
            return [self._fallback_one(e) for e in batch]

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return [self._fallback_one(e) for e in batch]

        self._record_tokens(ctx, payload, len(batch))
        parsed = _parse_scores(payload)
        return self._align(batch, parsed)

    # -- helpers ------------------------------------------------------------- #

    def _align(
        self, batch: list[str], parsed: dict[str, tuple[float, str]]
    ) -> list[tuple[str, float, str]]:
        """Match parsed rows back to input emails; heuristic-fill anything missing."""
        out: list[tuple[str, float, str]] = []
        for email in batch:
            hit = parsed.get(email.strip().lower())
            if hit is None:
                out.append(self._fallback_one(email))
            else:
                score, reason = hit
                out.append((email, score, reason))
        return out

    def _fallback_one(self, email: str) -> tuple[str, float, str]:
        e, score, reason = self._fallback._score_one(email)
        return e, score, f"{_FALLBACK_TAG}: {reason}"

    @staticmethod
    def _record_tokens(ctx: SourceRunContext, payload: dict[str, Any], batch_len: int) -> None:
        usage = payload.get("usage") if isinstance(payload, dict) else None
        tokens = 0
        if isinstance(usage, dict):
            tokens = int(usage.get("total_tokens") or 0)
        # Record token count as request_count so APIUsage reflects real token spend.
        ctx.record_usage(
            "groq",
            "chat.completions",
            unit_cost=_UNIT_COST_PER_TOKEN,
            request_count=max(tokens, batch_len),
        )


def _parse_scores(payload: dict[str, Any]) -> dict[str, tuple[float, str]]:
    """Extract {email_lower: (score, reason)} from a Groq chat-completion payload.

    Tolerant of the two common shapes the model returns: ``{"results": [...]}``
    or a bare top-level list. Bad/out-of-range scores are dropped so ``_align``
    heuristic-fills them.
    """
    content = _message_content(payload)
    if content is None:
        return {}
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}

    rows = data.get("results") if isinstance(data, dict) else data
    # Some models wrap under a different single key — take the first list value.
    if not isinstance(rows, list) and isinstance(data, dict):
        rows = next((v for v in data.values() if isinstance(v, list)), None)
    if not isinstance(rows, list):
        return {}

    out: dict[str, tuple[float, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = row.get("email")
        if not isinstance(email, str) or "@" not in email:
            continue
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            continue
        if not (0.0 <= score <= 1.0):
            continue
        reason = row.get("reason")
        reason = reason.strip() if isinstance(reason, str) and reason.strip() else "llm score"
        out[email.strip().lower()] = (round(score, 3), reason)
    return out


def _message_content(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None
