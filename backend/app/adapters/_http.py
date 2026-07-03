"""Shared async HTTP helpers for real provider adapters.

Every outbound call flows through ``audited_get``/``audited_request`` so the
SourceRunContext's Data_Source_Audit trail stays structural (spec §8): the
adapter never touches ``httpx`` directly. A non-2xx response is audited with an
``error`` status; a 429 (or 5xx) is surfaced as ``ProviderRateLimited`` so the
worker/adapter can back off and (for the LLM/verifier) fall back to the mock.

The helpers deliberately keep no global client: a short-lived ``AsyncClient`` is
opened per call. Real provider traffic is low-QPS (one lookup / one verify /
one batch), so connection-pool reuse is not worth the lifecycle complexity here,
and per-call clients keep the adapters trivially testable with ``respx``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = [
    "ProviderError",
    "ProviderRateLimited",
    "audited_request",
]


class ProviderError(Exception):
    """A non-retryable provider failure (4xx other than 429, or bad payload)."""


class ProviderRateLimited(ProviderError):
    """A retryable provider failure — HTTP 429 or 5xx. Caller should back off."""


async def audited_request(
    ctx: SourceRunContext,
    method: str,
    url: str,
    *,
    audit_url: str | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: Any | None = None,
    timeout: float = 20.0,
    records_found: int = 1,
) -> httpx.Response:
    """Perform one audited HTTP call and return the raw ``httpx.Response``.

    ``audit_url`` (defaulting to ``url``) is what lands in Data_Source_Audit — pass
    a key-free variant so secrets never enter the audit trail. Raises
    ``ProviderRateLimited`` on 429/5xx and ``ProviderError`` on other non-2xx.
    """
    trail = audit_url if audit_url is not None else url
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=headers, params=params, json=json)
    except httpx.HTTPError as exc:  # connect/read timeout, DNS, etc.
        ctx.audit(trail, status="error", error=str(exc))
        raise ProviderRateLimited(f"transport error: {exc}") from exc

    if response.status_code == 429 or response.status_code >= 500:
        ctx.audit(
            trail,
            status="error",
            error=f"HTTP {response.status_code}",
        )
        raise ProviderRateLimited(f"HTTP {response.status_code} from {trail}")
    if response.status_code >= 400:
        ctx.audit(trail, status="error", error=f"HTTP {response.status_code}")
        raise ProviderError(f"HTTP {response.status_code} from {trail}")

    ctx.audit(trail, status="ok", records_found=records_found)
    return response
