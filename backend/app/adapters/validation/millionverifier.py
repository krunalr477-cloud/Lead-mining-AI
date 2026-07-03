"""Real MillionVerifier email-verification adapter (spec §11 stage 6).

Endpoint: ``GET https://api.millionverifier.com/api/v3/?api=<KEY>&email=<EMAIL>``.
MillionVerifier returns a JSON body whose ``result`` field is one of
``ok``/``valid`` | ``invalid`` | ``catch_all`` | ``unknown`` | ``disposable`` |
``risky`` (naming varies slightly across plan tiers); we normalize to the five
``MillionVerifierStatus`` values the decision machine understands:

    ok / valid        -> VALID
    invalid           -> INVALID
    catch_all         -> CATCH_ALL
    unknown           -> UNKNOWN
    disposable        -> INVALID   (a throwaway mailbox is not deliverable to a lead)
    risky / risk      -> RISK

``verify`` returns ``(status.value, raw_dict)`` — the raw provider body is stored
for audit/debug. Results are cached per email for 30 days so a re-validation
inside the window spends no credit; each live call records one
``millionverifier`` credit and is audited (key-free).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.adapters._cache import MILLIONVERIFIER_TTL, cache_get, cache_key, cache_set
from app.adapters._http import ProviderError, ProviderRateLimited, audited_request
from app.adapters.base import EmailVerifierAdapter
from app.config import get_settings
from app.constants import MillionVerifierStatus

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["MillionVerifierAdapter"]

_VERIFY_URL = "https://api.millionverifier.com/api/v3/"
_UNIT_COST = 0.0008  # one verification credit (approx. USD).

# Provider ``result`` string -> normalized status. Keys are lowercased.
_RESULT_MAP: dict[str, MillionVerifierStatus] = {
    "ok": MillionVerifierStatus.VALID,
    "valid": MillionVerifierStatus.VALID,
    "invalid": MillionVerifierStatus.INVALID,
    "catch_all": MillionVerifierStatus.CATCH_ALL,
    "catchall": MillionVerifierStatus.CATCH_ALL,
    "unknown": MillionVerifierStatus.UNKNOWN,
    "disposable": MillionVerifierStatus.INVALID,
    "risky": MillionVerifierStatus.RISK,
    "risk": MillionVerifierStatus.RISK,
}


def map_result(result: str | None) -> MillionVerifierStatus:
    """Map a provider ``result`` string to a ``MillionVerifierStatus``.

    An unrecognized/absent result is treated as UNKNOWN (retry later) rather than
    silently passing — never fabricate a VALID we didn't get.
    """
    if not result:
        return MillionVerifierStatus.UNKNOWN
    return _RESULT_MAP.get(result.strip().lower(), MillionVerifierStatus.UNKNOWN)


class MillionVerifierAdapter(EmailVerifierAdapter):
    """Live MillionVerifier check. Activates only when the API key resolves."""

    provider = "millionverifier"
    required_credentials = ["MILLIONVERIFIER_API_KEY"]

    async def verify(self, email: str, ctx: SourceRunContext) -> tuple[str, dict[str, Any]]:
        normalized_email = (email or "").strip()
        settings = get_settings()
        api_key = settings.millionverifier_api_key
        if not normalized_email or not api_key:
            return MillionVerifierStatus.UNKNOWN.value, {"result": "unknown", "reason": "no input"}

        key = cache_key("millionverifier", normalized_email.lower())
        cached = cache_get(ctx, key)
        if cached is not None:
            status = map_result(cached.get("result"))
            return status.value, cached

        params = {"api": api_key, "email": normalized_email}
        audit_url = f"millionverifier:verify?email={normalized_email}"

        try:
            response = await audited_request(
                ctx,
                "GET",
                _VERIFY_URL,
                audit_url=audit_url,
                params=params,
            )
        except ProviderRateLimited:
            # Throttled/5xx — retry later, don't spend a credit, don't raise.
            return MillionVerifierStatus.UNKNOWN.value, {
                "result": "unknown",
                "reason": "rate_limited",
            }
        except ProviderError as exc:
            return MillionVerifierStatus.UNKNOWN.value, {
                "result": "unknown",
                "reason": f"provider_error: {exc}",
            }

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return MillionVerifierStatus.UNKNOWN.value, {
                "result": "unknown",
                "reason": "unparseable_body",
            }

        ctx.record_usage("millionverifier", "email.verify", unit_cost=_UNIT_COST)
        cache_set(ctx, key, payload, MILLIONVERIFIER_TTL)
        status = map_result(payload.get("result"))
        return status.value, payload
