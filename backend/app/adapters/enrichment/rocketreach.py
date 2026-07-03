"""Real RocketReach enrichment adapter (spec §10).

RocketReach's person lookup takes a name + current employer / domain (+ optional
title) and returns a contact with an email, phone, LinkedIn URL and other social
profiles. We map its response to ``ExtractedContact`` *candidates* and let the
caller (``stages.run_enrichment``) merge — this adapter NEVER decides to
overwrite existing higher-confidence data (spec §10 "do not overwrite
higher-confidence verified data"); it only proposes.

Compliance / cost (spec §10):
- Results are cached 90 days by (domain, person_name) in Redis so a re-run never
  spends a second credit.
- Every call records one ``rocketreach`` credit via ``ctx.record_usage`` and is
  audited (key-free) via the shared HTTP helper.
- 429 / 5xx are transient (``ProviderRateLimited``): the adapter returns no
  candidates rather than raising, so one throttled lookup can't fail the job.

Endpoint: ``GET https://api.rocketreach.co/api/v2/person/lookup`` with header
``Api-Key: <key>`` and query params ``name``, ``current_employer`` (company),
``current_title`` (designation) and ``current_employer_domain`` (domain). The raw
payload is stored on the returned candidate's ``source_snippet``/raw for audit.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.adapters._cache import ROCKETREACH_TTL, cache_get, cache_key, cache_set
from app.adapters._http import ProviderError, ProviderRateLimited, audited_request
from app.adapters.base import EnrichmentAdapter, ExtractedContact
from app.config import get_settings

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["RocketReachAdapter"]

_LOOKUP_URL = "https://api.rocketreach.co/api/v2/person/lookup"
_UNIT_COST = 0.10  # one lookup credit (approx. USD), tracked for cost estimation.


class RocketReachAdapter(EnrichmentAdapter):
    """Live RocketReach person lookup. Activates only when the API key resolves."""

    provider = "rocketreach"
    required_credentials = ["ROCKETREACH_API_KEY"]

    async def enrich(
        self,
        *,
        company_name: str,
        domain: str | None,
        website: str | None,
        person_name: str | None,
        designation: str | None,
        location: str | None,
        ctx: SourceRunContext,
    ) -> list[ExtractedContact]:
        # Need at least a person + a company/domain anchor to look anyone up.
        if not person_name or not (domain or company_name):
            return []

        settings = get_settings()
        api_key = settings.rocketreach_api_key
        if not api_key:  # resolver should prevent this, but stay defensive.
            return []

        key = cache_key("rocketreach", domain or company_name, person_name)
        cached = cache_get(ctx, key)
        if cached is not None:
            # A cached lookup spends no credit and touches no network.
            return self._map_payload(cached, person_name, designation)

        params: dict[str, Any] = {"name": person_name}
        if company_name:
            params["current_employer"] = company_name
        if domain:
            params["current_employer_domain"] = domain
        if designation:
            params["current_title"] = designation

        headers = {"Api-Key": api_key, "Accept": "application/json"}
        audit_url = f"rocketreach:person/lookup?name={person_name}&domain={domain or ''}"

        try:
            response = await audited_request(
                ctx,
                "GET",
                _LOOKUP_URL,
                audit_url=audit_url,
                headers=headers,
                params=params,
            )
        except ProviderRateLimited:
            # Throttled/5xx — transient. Don't spend the (failed) credit, don't raise.
            return []
        except ProviderError:
            # 4xx (e.g. 404 no match): count the credit, cache the empty result.
            ctx.record_usage("rocketreach", "person.lookup", unit_cost=_UNIT_COST)
            cache_set(ctx, key, {"status": "not_found"}, ROCKETREACH_TTL)
            return []

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return []

        ctx.record_usage("rocketreach", "person.lookup", unit_cost=_UNIT_COST)
        cache_set(ctx, key, payload, ROCKETREACH_TTL)
        return self._map_payload(payload, person_name, designation)

    # -- mapping ------------------------------------------------------------- #

    @staticmethod
    def _map_payload(
        payload: dict[str, Any], person_name: str, designation: str | None
    ) -> list[ExtractedContact]:
        """Map a RocketReach person payload -> ExtractedContact candidate(s)."""
        if not isinstance(payload, dict) or payload.get("status") == "not_found":
            return []

        email = _best_email(payload)
        phone = _best_phone(payload)
        linkedin = payload.get("linkedin_url") or _social(payload, "linkedin")
        facebook = _social(payload, "facebook")
        title = payload.get("current_title") or designation
        full_name = payload.get("name") or person_name

        # Nothing actionable came back — no candidate.
        if not (email or phone or linkedin):
            return []

        contact = ExtractedContact(
            full_name=full_name,
            first_name=payload.get("first_name"),
            last_name=payload.get("last_name"),
            designation=title,
            email=email,
            phone=phone,
            linkedin_url=linkedin,
            facebook_url=facebook,
            source_type="enrichment",
            source_snippet=(
                f"RocketReach lookup for {full_name}"
                + (
                    f" @ {payload.get('current_employer')}"
                    if payload.get("current_employer")
                    else ""
                )
            ),
            confidence_score=_confidence(payload, email),
            is_demo=False,
        )
        return [contact]


# --------------------------------------------------------------------------- #
# Payload extraction helpers (RocketReach response shapes vary by plan/route).
# --------------------------------------------------------------------------- #


def _best_email(payload: dict[str, Any]) -> str | None:
    """Prefer the top-level ``current_work_email``/``email``; else the first grade
    'valid'/highest-SMTP email from the ``emails`` list."""
    for field in ("current_work_email", "email", "recommended_email"):
        value = payload.get(field)
        if isinstance(value, str) and "@" in value:
            return value.strip()

    emails = payload.get("emails")
    if isinstance(emails, list):
        # Sort valid-graded first, then professional over personal.
        def rank(entry: dict[str, Any]) -> tuple[int, int]:
            grade = str(entry.get("smtp_valid") or entry.get("grade") or "").lower()
            valid = 0 if grade in {"valid", "a", "a+"} else 1
            professional = 0 if entry.get("type") == "professional" else 1
            return (valid, professional)

        candidates = [e for e in emails if isinstance(e, dict) and e.get("email")]
        for entry in sorted(candidates, key=rank):
            value = entry.get("email")
            if isinstance(value, str) and "@" in value:
                return value.strip()
    return None


def _best_phone(payload: dict[str, Any]) -> str | None:
    phone = payload.get("current_work_phone") or payload.get("phone")
    if isinstance(phone, str) and phone.strip():
        return phone.strip()
    phones = payload.get("phones")
    if isinstance(phones, list):
        for entry in phones:
            if isinstance(entry, dict) and entry.get("number"):
                return str(entry["number"]).strip()
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
    return None


def _social(payload: dict[str, Any], network: str) -> str | None:
    links = payload.get("links")
    if isinstance(links, dict):
        value = links.get(network)
        if isinstance(value, str) and value.strip():
            return value.strip()
    profiles = payload.get("profiles")
    if isinstance(profiles, list):
        for entry in profiles:
            if isinstance(entry, dict) and str(entry.get("network", "")).lower() == network:
                url = entry.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
    return None


def _confidence(payload: dict[str, Any], email: str | None) -> float:
    """Derive a [0,1] confidence from RocketReach's own grade signals.

    A 'valid'/'A' graded work email is high-confidence; a guessed/personal email
    is lower; no email (phone/linkedin only) is lowest.
    """
    if not email:
        return 0.4
    grade = ""
    emails = payload.get("emails")
    if isinstance(emails, list):
        for entry in emails:
            if isinstance(entry, dict) and entry.get("email") == email:
                grade = str(entry.get("smtp_valid") or entry.get("grade") or "").lower()
                break
    if grade in {"valid", "a", "a+"}:
        return 0.9
    if grade in {"b", "risky"}:
        return 0.7
    if grade in {"invalid", "f"}:
        return 0.5
    # Top-level work email with no per-email grade — still a solid signal.
    if payload.get("current_work_email") == email:
        return 0.8
    return 0.6
