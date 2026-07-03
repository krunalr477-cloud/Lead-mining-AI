"""Mock enrichment / verifier / LLM-scorer providers (deterministic).

- MockRocketReachAdapter.enrich  — mints a plausible person email for a contact
  that is missing one, seeded from company+person so it is stable.
- MockMillionVerifierAdapter.verify — buckets an email into valid/invalid/
  catch_all/risk/unknown from a stable hash, so the same address always lands
  in the same bucket (and the demo funnel is realistic and reproducible).
- MockGroqScorerAdapter.score — a heuristic confidence score in [0,1] per email,
  lower for suspicious/role/random-looking locals.

Every provider records usage + audit through the SourceRunContext so the demo
run's cost/audit trail matches a real run's shape.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.adapters.base import (
    EmailVerifierAdapter,
    EnrichmentAdapter,
    ExtractedContact,
    LLMScorerAdapter,
)
from app.adapters.mock._common import rng_from, stable_unit
from app.constants import MillionVerifierStatus

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = [
    "MockGroqScorerAdapter",
    "MockMillionVerifierAdapter",
    "MockRocketReachAdapter",
]

_ROLE_LOCALS = {"info", "contact", "admin", "office", "ca", "sales", "support", "hr"}


class MockRocketReachAdapter(EnrichmentAdapter):
    provider = "rocketreach"
    required_credentials = ["rocketreach_api_key"]

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
        ctx.audit(
            f"rocketreach:lookup?name={person_name or ''}&domain={domain or ''}",
            status="ok",
            records_found=1 if person_name and domain else 0,
        )
        ctx.record_usage("rocketreach", "person.lookup", unit_cost=0.10)

        if not person_name or not domain:
            return []
        # Enrichment recovers only a share of the email-less contacts, so the demo
        # funnel lands near spec §21's "73% emails found" (the rest stay email-less
        # and never reach validation / sales-ready).
        if stable_unit(person_name, domain, "miss") < 0.65:
            return []

        rng = rng_from(person_name, domain, "rr")
        parts = person_name.split()
        first = parts[0].lower() if parts else "contact"
        last = parts[-1].lower() if len(parts) > 1 else "team"
        local = rng.choice([f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}"])
        email = f"{local}@{domain}"
        return [
            ExtractedContact(
                full_name=person_name,
                designation=designation,
                email=email,
                source_type="enrichment",
                source_snippet=f"RocketReach match for {person_name} @ {domain}",
                confidence_score=round(0.55 + 0.4 * stable_unit(email, "conf"), 3),
                is_demo=True,
            )
        ]


class MockMillionVerifierAdapter(EmailVerifierAdapter):
    provider = "millionverifier"
    required_credentials = ["millionverifier_api_key"]

    async def verify(self, email: str, ctx: SourceRunContext) -> tuple[str, dict[str, Any]]:
        ctx.audit(f"millionverifier:verify?email={email}", status="ok", records_found=1)
        ctx.record_usage("millionverifier", "email.verify", unit_cost=0.0008)

        u = stable_unit(email.strip().lower(), "mv")
        # Distribution tuned so the demo funnel lands near spec §21 (most found,
        # non-role, non-disposable person emails verify VALID), with a realistic
        # tail of catch-all/risk/unknown/invalid to exercise every review path.
        if u < 0.965:
            status = MillionVerifierStatus.VALID
        elif u < 0.978:
            status = MillionVerifierStatus.CATCH_ALL
        elif u < 0.988:
            status = MillionVerifierStatus.RISK
        elif u < 0.995:
            status = MillionVerifierStatus.UNKNOWN
        else:
            status = MillionVerifierStatus.INVALID

        payload = {
            "email": email,
            "result": status.value,
            "quality_score": round(u, 4),
            "provider": "millionverifier-mock",
        }
        return status.value, payload


class MockGroqScorerAdapter(LLMScorerAdapter):
    provider = "groq"
    required_credentials = ["groq_api_key"]

    async def score(self, emails: list[str], ctx: SourceRunContext) -> list[tuple[str, float, str]]:
        ctx.audit("groq:chat.completions", status="ok", records_found=len(emails))
        ctx.record_usage(
            "groq", "chat.completions", unit_cost=0.0002, request_count=max(1, len(emails))
        )

        out: list[tuple[str, float, str]] = []
        for email in emails:
            out.append(self._score_one(email))
        return out

    @staticmethod
    def _score_one(email: str) -> tuple[str, float, str]:
        base = stable_unit(email.strip().lower(), "llm")
        local = email.split("@", 1)[0].lower() if "@" in email else email.lower()
        score = 0.4 + 0.55 * base
        reasons = []
        if local in _ROLE_LOCALS:
            score -= 0.25
            reasons.append("role-inbox local part")
        if re.fullmatch(r"[a-z]{1,3}\d{2,}", local):
            score -= 0.2
            reasons.append("random-looking local part")
        if "." in local or "_" in local:
            score += 0.05
            reasons.append("name-like local part")
        score = max(0.0, min(1.0, score))
        reason = "; ".join(reasons) or "plausible personal address"
        return email, round(score, 3), reason
