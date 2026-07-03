"""Pure sales-ready eligibility + ranking rules (spec §12, acceptance §25).

The single hard rule (spec §11/§12/§25, non-negotiable rule "never expose invalid
emails to sales-ready output"): a contact is sales-ready ONLY when its final email
status is exactly VERIFIED and it is not suppressed, hard-bounced, or unsubscribed.
Every other FinalEmailStatus — including the review states — is excluded.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.constants import FinalEmailStatus

__all__ = ["is_sales_ready", "rank_key"]


def is_sales_ready(
    contact_final_status: FinalEmailStatus | str | None,
    *,
    suppressed: bool = False,
    bounced: bool = False,
    unsubscribed: bool = False,
    role_based: bool = False,
    allow_role_based: bool = False,
    disposable: bool = False,
    mx_ok: bool = True,
    provider_invalid: bool = False,
) -> bool:
    """True only if the contact may appear in Sales_Ready_Leads (spec §12/§25).

    ``contact_final_status`` must be exactly ``VERIFIED``. The remaining flags are
    belt-and-suspenders gates: even a row stored as VERIFIED is excluded if it is
    suppressed/bounced/unsubscribed, or if any raw disqualifier is set (disposable,
    provider-invalid, MX not ok, or a role inbox the tenant doesn't allow). This
    guarantees no invalid/review/suppressed email can ever leak into clean output.
    """
    # Normalize to the enum value string.
    status = (
        contact_final_status.value
        if isinstance(contact_final_status, FinalEmailStatus)
        else contact_final_status
    )
    if status != FinalEmailStatus.VERIFIED.value:
        return False

    # Post-send / list-hygiene exclusions.
    if suppressed or bounced or unsubscribed:
        return False

    # Raw disqualifiers — defensive against inconsistent upstream state.
    if disposable or provider_invalid or not mx_ok:
        return False
    if role_based and not allow_role_based:
        return False

    return True


def _as_float(value: Any) -> float:
    """Coerce a confidence score (float/Decimal/str/None) to a float in [0, ~1]."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# Role-relevance ordering (spec §9/§12: prefer role-matched decision makers).
# Higher rank = more relevant. Unlisted roles fall to 0.
_ROLE_RELEVANCE = {
    "founder": 100,
    "ceo": 95,
    "owner": 92,
    "managing_partner": 90,
    "managing partner": 90,
    "managing_director": 88,
    "managing director": 88,
    "partner": 85,
    "principal": 80,
    "director": 78,
    "vp_sales": 72,
    "vp sales": 72,
    "cto": 70,
    "cfo": 70,
    "operations_head": 65,
    "operations head": 65,
    "decision_maker": 60,
    "department_head": 55,
}


def _role_relevance(contact: Mapping[str, Any]) -> int:
    for key in ("role_category", "seniority", "designation"):
        raw = contact.get(key)
        if isinstance(raw, str) and raw.strip():
            score = _ROLE_RELEVANCE.get(raw.strip().lower())
            if score is not None:
                return score
    return 0


def rank_key(contact: Mapping[str, Any]) -> tuple:
    """Sort key for sales-ready output (spec §12 sort order).

    Ordering (all descending — sort with ``reverse=True`` OR negate as done here):
      1. primary_contact          (True first)
      2. email verification confidence (confidence_score desc)
      3. role relevance           (decision-makers first)
      4. recency of validation    (most recently verified first)

    Returned as a tuple of values where LARGER == RANKS-HIGHER, so callers use
    ``sorted(contacts, key=rank_key, reverse=True)`` to get best leads first.
    Company fit / source confidence (spec §12 items 4-5) are folded in as lower-
    priority tiebreakers when present on the contact mapping.
    """
    primary = 1 if contact.get("primary_contact") else 0
    confidence = _as_float(contact.get("confidence_score"))
    relevance = _role_relevance(contact)

    # Recency: convert last_verified_at to a sortable epoch-ish number; missing -> 0.
    recency = 0.0
    lv = contact.get("last_verified_at")
    if lv is not None:
        ts = getattr(lv, "timestamp", None)
        if callable(ts):
            try:
                recency = lv.timestamp()
            except (OSError, OverflowError, ValueError):
                recency = 0.0
        elif isinstance(lv, (int, float)):
            recency = float(lv)

    company_fit = _as_float(contact.get("company_fit"))
    source_confidence = _as_float(contact.get("source_confidence"))

    return (primary, confidence, relevance, company_fit, source_confidence, recency)
