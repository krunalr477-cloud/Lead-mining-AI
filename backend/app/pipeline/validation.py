"""Pure email-validation stage functions and the final-decision machine (spec §11).

Six stages, each a pure function:
  1. check_syntax          -> bool
  2. check_disposable      -> bool
  3. is_role_based         -> bool
  4. check_mx              -> (StageStatus, detail)
  5. LLM score             -> supplied by caller (LLMScorerAdapter)
  6. MillionVerifier       -> supplied by caller (EmailVerifierAdapter)

`decide()` folds all six signals plus suppression into exactly one FinalEmailStatus
following the precedence in spec §11 ("Final decision logic" / "Final statuses").

NOTHING here imports Celery, SQLAlchemy, or performs I/O beyond the injected DNS
resolver. `check_mx` raises a local ``ValidationTransient`` for retryable DNS
conditions; the worker layer translates that into a Celery ``TransientError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app.constants import (
    DEFAULT_ROLE_KEYWORDS,
    FinalEmailStatus,
    MillionVerifierStatus,
    StageStatus,
)

__all__ = [
    "ValidationTransient",
    "RuleSet",
    "Resolver",
    "check_syntax",
    "check_disposable",
    "is_role_based",
    "check_mx",
    "decide",
]


class ValidationTransient(Exception):
    """Retryable DNS/verification failure (Timeout, SERVFAIL, no-nameservers).

    Defined locally so this module stays free of Celery imports. The worker that
    calls ``check_mx`` catches this and re-raises the queue-layer ``TransientError``
    so the job is retried with backoff instead of being marked permanently failed.
    """


# --------------------------------------------------------------------------- #
# RuleSet — loaded from ValidationRuleSet.rules JSON
# --------------------------------------------------------------------------- #

# Accepted literal values, mirrored from the Validation Rules Settings screen.
_LLM_MODES = frozenset({"advisory", "hard"})
_CATCH_ALL_POLICIES = frozenset({"review", "allow"})
_RISK_POLICIES = frozenset({"review", "reject"})

_DEFAULT_UNKNOWN_RETRY = {"max_attempts": 3, "delay_hours": 6}


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Tenant validation policy, decoded from ``ValidationRuleSet.rules`` (spec §11/§17).

    Defaults match the task contract. ``from_dict`` is tolerant: unknown keys are
    ignored and out-of-range/garbage values fall back to the safe default so a
    malformed settings row can never crash the pipeline or silently open a gate.
    """

    llm_threshold: float = 0.55
    llm_mode: str = "advisory"  # 'advisory' (soft/informational) | 'hard' (rejecting gate)
    role_keywords: tuple[str, ...] = tuple(DEFAULT_ROLE_KEYWORDS)
    allow_role_based: bool = False
    catch_all_policy: str = "review"  # 'review' | 'allow'
    risk_policy: str = "review"  # 'review' | 'reject'
    unknown_retry: dict = field(default_factory=lambda: dict(_DEFAULT_UNKNOWN_RETRY))

    @classmethod
    def from_dict(cls, raw: dict | None) -> RuleSet:
        raw = raw or {}

        # llm_threshold: clamp to [0, 1]; non-numeric -> default.
        try:
            threshold = float(raw.get("llm_threshold", 0.55))
        except (TypeError, ValueError):
            threshold = 0.55
        threshold = min(1.0, max(0.0, threshold))

        # llm_mode: the ValidationRuleSet default seeds 'adjudicate'; treat any value
        # that is not the explicit hard-gate keyword as advisory (soft) so a stored
        # 'adjudicate'/'soft'/typo never accidentally rejects mail.
        llm_mode = str(raw.get("llm_mode", "advisory")).lower()
        if llm_mode not in _LLM_MODES:
            llm_mode = "advisory"

        keywords_raw = raw.get("role_keywords") or DEFAULT_ROLE_KEYWORDS
        role_keywords = tuple(
            k.strip().lower() for k in keywords_raw if isinstance(k, str) and k.strip()
        )
        if not role_keywords:
            role_keywords = tuple(DEFAULT_ROLE_KEYWORDS)

        catch_all_policy = str(raw.get("catch_all_policy", "review")).lower()
        if catch_all_policy not in _CATCH_ALL_POLICIES:
            catch_all_policy = "review"

        risk_policy = str(raw.get("risk_policy", "review")).lower()
        if risk_policy not in _RISK_POLICIES:
            risk_policy = "review"

        unknown_raw = raw.get("unknown_retry")
        unknown_retry = dict(_DEFAULT_UNKNOWN_RETRY)
        if isinstance(unknown_raw, dict):
            unknown_retry.update(
                {k: v for k, v in unknown_raw.items() if k in _DEFAULT_UNKNOWN_RETRY}
            )
        elif isinstance(unknown_raw, int) and not isinstance(unknown_raw, bool):
            # ValidationRuleSet.default_validation_rules() seeds a bare int; treat it
            # as max_attempts for backward compatibility.
            unknown_retry["max_attempts"] = unknown_raw

        return cls(
            llm_threshold=threshold,
            llm_mode=llm_mode,
            role_keywords=role_keywords,
            allow_role_based=bool(raw.get("allow_role_based", False)),
            catch_all_policy=catch_all_policy,
            risk_policy=risk_policy,
            unknown_retry=unknown_retry,
        )


# --------------------------------------------------------------------------- #
# Stage 1 — syntax
# --------------------------------------------------------------------------- #


def check_syntax(email: str) -> bool:
    """True if ``email`` is syntactically valid (spec §11 stage 1).

    Deliverability (MX) is checked separately in stage 4, so we disable it here.
    """
    if not isinstance(email, str) or not email.strip():
        return False
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return False
    return True


# --------------------------------------------------------------------------- #
# Stage 2 — disposable domain
# --------------------------------------------------------------------------- #

# Loaded once at import. The maintained package ships a frozenset of ~7.8k domains;
# tenants may extend it via ``extra_domains`` (spec §11 stage 2 "make the list updateable").
try:  # pragma: no cover - import shape guard
    from disposable_email_domains import blocklist as _DISPOSABLE_BLOCKLIST
except ImportError:  # pragma: no cover
    _DISPOSABLE_BLOCKLIST = frozenset()


def _domain_of(email: str) -> str | None:
    if not isinstance(email, str) or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower().rstrip(".")
    return domain or None


def check_disposable(email: str, extra_domains: set[str] | None = None) -> bool:
    """True if the email's domain is a known throwaway/disposable domain (rejectable).

    Combines the maintained package blocklist with tenant-supplied ``extra_domains``.
    An unparseable address is treated as NOT disposable here — syntax stage owns that
    rejection; this stage only speaks to the disposable signal.
    """
    domain = _domain_of(email)
    if domain is None:
        return False
    if domain in _DISPOSABLE_BLOCKLIST:
        return True
    if extra_domains:
        normalized = {d.strip().lower().rstrip(".") for d in extra_domains if d}
        if domain in normalized:
            return True
    return False


# --------------------------------------------------------------------------- #
# Stage 3 — role-based inbox
# --------------------------------------------------------------------------- #


def is_role_based(email: str, role_keywords: list[str] | tuple[str, ...] | None = None) -> bool:
    """True if the local part is a role inbox (info@, sales@, ...) — spec §11 stage 3.

    Matching is on the *local part*, split on ``. _ - +`` tokens so ``sales@`` and
    ``sales.team@`` and ``jobs+eu@`` all match while ``salesforce@`` (a plausible
    person/handle) does not. ``john@`` never matches the default keywords.
    """
    keywords = role_keywords if role_keywords is not None else DEFAULT_ROLE_KEYWORDS
    keyword_set = {k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()}
    if not keyword_set:
        return False
    if not isinstance(email, str) or "@" not in email:
        return False
    local = email.rsplit("@", 1)[0].strip().lower()
    if not local:
        return False
    if local in keyword_set:
        return True
    # Tokenize on common separators to catch compound role locals without
    # firing on substrings inside a real name.
    tokens = local.replace(".", " ").replace("_", " ").replace("-", " ").replace("+", " ").split()
    return any(token in keyword_set for token in tokens)


# --------------------------------------------------------------------------- #
# Stage 4 — MX record
# --------------------------------------------------------------------------- #


class Resolver(Protocol):
    """Minimal shape of ``dns.resolver.Resolver`` used by ``check_mx`` (test injection)."""

    def resolve(self, qname: str, rdtype: str):  # pragma: no cover - protocol
        ...


def _default_resolver() -> dns.resolver.Resolver:
    r = dns.resolver.Resolver()
    r.lifetime = 5.0
    r.timeout = 5.0
    return r


def check_mx(domain: str, resolver: Resolver | None = None) -> tuple[StageStatus, str]:
    """Check whether ``domain`` can accept mail (spec §11 stage 4).

    Resolution order: MX records first; if the domain has no MX but does have an
    A/AAAA address, mail is still deliverable to that host (implicit MX, RFC 5321
    §5.1), so that is a PASS.

    Returns ``(StageStatus, human-readable detail)``:
      - PASS  — MX present, or A/AAAA fallback present.
      - FAIL  — NXDOMAIN (domain doesn't exist) or NoAnswer with no address fallback.
    Raises ``ValidationTransient`` for retryable failures: Timeout, SERVFAIL
    (``dns.resolver.NoNameservers``), and generic DNS exceptions — the caller retries.
    """
    if not isinstance(domain, str) or not domain.strip():
        return StageStatus.FAIL, "empty domain"
    domain = domain.strip().rstrip(".").lower()

    r = resolver or _default_resolver()

    # --- MX lookup ---
    try:
        answers = r.resolve(domain, "MX")
        exchanges = [str(rr.exchange).rstrip(".") for rr in answers]
        exchanges = [e for e in exchanges if e]
        if exchanges:
            return StageStatus.PASS, f"MX: {', '.join(sorted(exchanges)[:5])}"
        # An MX rrset that resolved to nothing usable -> fall through to A/AAAA.
    except dns.resolver.NXDOMAIN:
        return StageStatus.FAIL, "NXDOMAIN: domain does not exist"
    except dns.resolver.NoAnswer:
        pass  # No MX rrset; try A/AAAA implicit-MX fallback below.
    except dns.resolver.NoNameservers as exc:  # SERVFAIL from all nameservers
        raise ValidationTransient(f"SERVFAIL for {domain}: {exc}") from exc
    except dns.exception.Timeout as exc:
        raise ValidationTransient(f"DNS timeout for {domain}: {exc}") from exc
    except dns.exception.DNSException as exc:
        raise ValidationTransient(f"DNS error for {domain}: {exc}") from exc

    # --- A / AAAA implicit-MX fallback ---
    for rdtype in ("A", "AAAA"):
        try:
            answers = r.resolve(domain, rdtype)
            if len(answers):
                return StageStatus.PASS, f"{rdtype} fallback (implicit MX)"
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.resolver.NoNameservers as exc:
            raise ValidationTransient(f"SERVFAIL for {domain} {rdtype}: {exc}") from exc
        except dns.exception.Timeout as exc:
            raise ValidationTransient(f"DNS timeout for {domain} {rdtype}: {exc}") from exc
        except dns.exception.DNSException as exc:
            raise ValidationTransient(f"DNS error for {domain} {rdtype}: {exc}") from exc

    return StageStatus.FAIL, "no MX and no A/AAAA fallback"


# --------------------------------------------------------------------------- #
# Final decision machine (spec §11)
# --------------------------------------------------------------------------- #


def decide(
    *,
    syntax_ok: bool,
    disposable_ok: bool,
    role_based: bool,
    mx_status: StageStatus,
    llm_score: float | None,
    mv_status: MillionVerifierStatus | None,
    suppressed: bool,
    rules: RuleSet,
) -> tuple[FinalEmailStatus, str]:
    """Fold every signal into one FinalEmailStatus + reason (spec §11 precedence).

    Parameters
    ----------
    syntax_ok      : stage-1 result (True = valid syntax).
    disposable_ok  : True when the domain is NOT disposable (i.e. the check passed).
    role_based     : True when the local part is a role inbox.
    mx_status      : stage-4 StageStatus (PASS/FAIL; REVIEW/SKIPPED/PENDING treated
                     as non-failing so an un-run MX stage never fabricates MX_FAILED).
    llm_score      : stage-5 score in [0,1], or None if the LLM stage did not run.
    mv_status      : MillionVerifier result, or None if stage-6 did not run.
    suppressed     : email/domain is on the suppression list.
    rules          : tenant RuleSet.

    Precedence (highest first) — exactly as spec §11 "Final decision logic":
      1. SUPPRESSED
      2. INVALID_SYNTAX
      3. DISPOSABLE_REJECTED
      4. ROLE_BASED_REJECTED       (skipped when rules.allow_role_based)
      5. MX_FAILED
      6. LLM_LOW_CONFIDENCE        (only when llm_mode == 'hard' and score < threshold)
      7. MillionVerifier mapping:
           invalid    -> PROVIDER_INVALID
           catch_all  -> CATCH_ALL_REVIEW  (unless catch_all_policy == 'allow' -> VERIFIED)
           risk       -> RISK_REVIEW       (or PROVIDER_INVALID when risk_policy == 'reject')
           unknown    -> UNKNOWN_RETRY
           valid      -> VERIFIED          (all hard gates already passed at this point)
           None       -> VERIFIED          (MV stage skipped; earlier hard gates passed)
    """
    # 1. Suppression trumps everything — never send to a suppressed address.
    if suppressed:
        return FinalEmailStatus.SUPPRESSED, "Email or domain is on the suppression list."

    # 2. Syntax hard gate.
    if not syntax_ok:
        return FinalEmailStatus.INVALID_SYNTAX, "Email failed syntax validation."

    # 3. Disposable hard gate (disposable_ok == True means the check passed).
    if not disposable_ok:
        return (
            FinalEmailStatus.DISPOSABLE_REJECTED,
            "Domain is a known disposable/throwaway provider.",
        )

    # 4. Role-based rejection, unless the tenant explicitly allows role inboxes.
    if role_based and not rules.allow_role_based:
        return (
            FinalEmailStatus.ROLE_BASED_REJECTED,
            "Role-based inbox rejected for sales-ready output.",
        )

    # 5. MX hard gate — only an explicit FAIL rejects. PENDING/REVIEW/SKIPPED do not.
    if mx_status == StageStatus.FAIL:
        return FinalEmailStatus.MX_FAILED, "Domain has no MX/A record accepting mail."

    # 6. LLM low-confidence — a hard gate ONLY in 'hard' mode. In 'advisory' mode
    #    the score is informational and never rejects (spec §11 stage 5).
    if rules.llm_mode == "hard" and llm_score is not None and llm_score < rules.llm_threshold:
        return (
            FinalEmailStatus.LLM_LOW_CONFIDENCE,
            f"LLM confidence {llm_score:.2f} below hard threshold {rules.llm_threshold:.2f}.",
        )

    # 7. MillionVerifier provider mapping. Reaching here means every hard gate passed.
    if mv_status is None:
        # MV stage not run (e.g. provider disabled); earlier hard gates all passed.
        return (
            FinalEmailStatus.VERIFIED,
            "All configured validation stages passed (verifier not run).",
        )

    if mv_status == MillionVerifierStatus.INVALID:
        return FinalEmailStatus.PROVIDER_INVALID, "MillionVerifier reported the mailbox as invalid."

    if mv_status == MillionVerifierStatus.CATCH_ALL:
        if rules.catch_all_policy == "allow":
            return FinalEmailStatus.VERIFIED, "Catch-all domain accepted by tenant policy."
        return FinalEmailStatus.CATCH_ALL_REVIEW, "Catch-all domain — needs review before sending."

    if mv_status == MillionVerifierStatus.RISK:
        if rules.risk_policy == "reject":
            return (
                FinalEmailStatus.PROVIDER_INVALID,
                "Risky address rejected by tenant risk policy.",
            )
        return FinalEmailStatus.RISK_REVIEW, "Risky address — needs review before sending."

    if mv_status == MillionVerifierStatus.UNKNOWN:
        return (
            FinalEmailStatus.UNKNOWN_RETRY,
            "MillionVerifier could not determine status — retry later.",
        )

    if mv_status == MillionVerifierStatus.VALID:
        return FinalEmailStatus.VERIFIED, "Verified: all hard gates passed and provider says valid."

    # Defensive: unrecognized provider status -> retry rather than falsely verifying.
    return FinalEmailStatus.UNKNOWN_RETRY, f"Unrecognized verifier status: {mv_status!r}."
