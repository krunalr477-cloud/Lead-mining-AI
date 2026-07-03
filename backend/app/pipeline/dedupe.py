"""Pure company/contact deduplication keys and merge semantics (spec §9).

Dedupe strategy (spec §9 "Deduplication"):
  - Companies dedupe by domain, then normalized name, then phone, then address.
  - Contacts dedupe by email, then name+company.
  - Merge source *evidence* rather than creating duplicate records; keep source URLs.

Every function here is pure: it takes plain values / dicts and returns plain values.
The worker layer resolves these keys against the DB and performs the actual upsert.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

__all__ = [
    "normalize_domain",
    "normalize_phone",
    "slug_name",
    "company_dedupe_key",
    "contact_dedupe_key",
    "SourceEvidence",
    "CompanyMergeResult",
    "ContactMergeResult",
    "merge_company_evidence",
    "merge_contact",
]

# Common corporate suffixes stripped before slugging so "Acme Inc" == "Acme, LLC".
_COMPANY_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "llp",
    "ltd",
    "limited",
    "pvt",
    "private",
    "plc",
    "co",
    "corp",
    "corporation",
    "company",
    "gmbh",
    "sa",
    "srl",
    "bv",
    "ag",
    "pty",
    "group",
    "holdings",
    "partners",
    "associates",
    "and",
    "the",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_NON_DIGIT_PLUS = re.compile(r"[^\d+]")


def normalize_domain(value: str | None) -> str | None:
    """Lowercase, strip scheme/path/port and a leading ``www.``.

    Accepts a bare domain, a full URL, or an email; returns the registrable host
    or None if nothing usable remains.
    """
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if "@" in v and "//" not in v:  # looks like an email
        v = v.rsplit("@", 1)[1]
    v = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", v)  # scheme
    v = v.split("/", 1)[0]  # path
    v = v.split("?", 1)[0].split("#", 1)[0]
    v = v.split("@", 1)[-1]  # userinfo in URL authority
    v = v.split(":", 1)[0]  # port
    v = v.strip().rstrip(".")
    if v.startswith("www."):
        v = v[4:]
    return v or None


def normalize_phone(value: str | None, default_region: str | None = None) -> str | None:
    """Best-effort E.164-ish normalization.

    Uses ``phonenumbers`` when the number parses (optionally with a default region);
    otherwise falls back to stripping to digits and a single leading ``+`` so two
    formattings of the same number still collide on the dedupe key.
    """
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        import phonenumbers

        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    # Fallback: keep leading + if present, then digits only.
    has_plus = raw.lstrip().startswith("+")
    digits = _NON_DIGIT_PLUS.sub("", raw).lstrip("+")
    if not digits:
        return None
    return ("+" if has_plus else "") + digits


def slug_name(value: str | None) -> str | None:
    """Slug a company/person name: strip accents, drop corporate suffixes, join tokens.

    "Acme Consulting, LLC" -> "acme-consulting"; "The Näme Co." -> "name".
    """
    if not value or not isinstance(value, str):
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    tokens = [t for t in _NON_ALNUM.split(lowered) if t]
    kept = [t for t in tokens if t not in _COMPANY_SUFFIXES]
    if not kept:  # name was entirely suffixes/stopwords — keep original tokens
        kept = tokens
    return "-".join(kept) or None


def company_dedupe_key(
    name: str | None,
    domain: str | None,
    phone: str | None,
    address: str | None,
) -> str | None:
    """Best available stable identity key for a company (spec §9 order).

    Priority: domain > normalized-name > phone > slugged-address. Returns a
    namespaced key so a domain key can never collide with a phone key.
    """
    d = normalize_domain(domain)
    if d:
        return f"domain:{d}"
    n = slug_name(name)
    if n:
        return f"name:{n}"
    p = normalize_phone(phone)
    if p:
        return f"phone:{p}"
    a = slug_name(address)
    if a:
        return f"addr:{a}"
    return None


def contact_dedupe_key(
    email: str | None,
    name: str | None,
    company_id: str | None,
) -> str | None:
    """Stable identity key for a contact (spec §9).

    Priority: email (globally unique) > normalized name scoped to the company.
    A name key requires a company_id so the same person at two firms stays distinct.
    """
    if email and isinstance(email, str) and email.strip():
        return f"email:{email.strip().lower()}"
    n = slug_name(name)
    if n and company_id:
        return f"name:{company_id}:{n}"
    return None


# --------------------------------------------------------------------------- #
# Merge semantics (pure) — return merged field set + evidence to add.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """One CompanySource row to add during a merge (spec §9 'keep source URLs')."""

    source_name: str
    source_url: str | None = None
    access_method: str | None = None
    compliance_posture: str | None = None


def _coalesce(existing, incoming):
    """Prefer a non-empty existing value; otherwise take incoming (fill-only merge)."""
    if existing not in (None, "", [], {}):
        return existing
    return incoming


@dataclass(slots=True)
class CompanyMergeResult:
    fields: dict = field(default_factory=dict)
    evidence: list[SourceEvidence] = field(default_factory=list)
    merged_source_urls: list[str] = field(default_factory=list)


def merge_company_evidence(
    existing: dict,
    incoming: dict,
    incoming_evidence: SourceEvidence | None = None,
) -> CompanyMergeResult:
    """Merge an incoming company sighting into the existing record (pure).

    Fill-only: existing non-empty fields win (never overwrite curated/higher-trust
    data). ``source_urls`` are unioned preserving first-seen order, and the incoming
    sighting becomes a new ``CompanySource`` evidence row. Nothing is persisted here —
    the caller applies ``fields``, appends ``evidence``, and sets ``source_urls``.
    """
    fields: dict = {}
    mergeable = set(existing) | set(incoming)
    mergeable.discard("source_urls")
    for key in mergeable:
        merged = _coalesce(existing.get(key), incoming.get(key))
        if merged != existing.get(key):
            fields[key] = merged

    # Union source_urls preserving order.
    seen: list[str] = []
    for url in list(existing.get("source_urls") or []) + list(incoming.get("source_urls") or []):
        if url and url not in seen:
            seen.append(url)

    evidence: list[SourceEvidence] = []
    if incoming_evidence is not None:
        evidence.append(incoming_evidence)
        if incoming_evidence.source_url and incoming_evidence.source_url not in seen:
            seen.append(incoming_evidence.source_url)

    return CompanyMergeResult(fields=fields, evidence=evidence, merged_source_urls=seen)


@dataclass(slots=True)
class ContactMergeResult:
    fields: dict = field(default_factory=dict)
    # New email candidates discovered for this contact (deduped, order-preserving).
    new_email_candidates: list[str] = field(default_factory=list)


def merge_contact(existing: dict, incoming: dict) -> ContactMergeResult:
    """Merge an incoming contact sighting into an existing contact (pure).

    Fill-only for scalar fields (do not clobber a verified/curated value with a
    lower-confidence sighting, spec §10). Confidence is taken as the max of the two.
    Any incoming email not already on the contact is surfaced as a new email
    candidate for the validation pipeline rather than overwriting ``email``.
    """
    fields: dict = {}
    scalar_keys = (set(existing) | set(incoming)) - {"confidence_score", "email"}
    for key in scalar_keys:
        merged = _coalesce(existing.get(key), incoming.get(key))
        if merged != existing.get(key):
            fields[key] = merged

    # Confidence: keep the strongest signal.
    ex_conf = existing.get("confidence_score")
    in_conf = incoming.get("confidence_score")
    confidences = [c for c in (ex_conf, in_conf) if isinstance(c, (int, float))]
    if confidences:
        best = max(confidences)
        if best != ex_conf:
            fields["confidence_score"] = best

    # Email: fill if empty, else record any new address as a candidate.
    new_candidates: list[str] = []
    ex_email = (existing.get("email") or "").strip().lower()
    in_email = (incoming.get("email") or "").strip().lower()
    if in_email:
        if not ex_email:
            fields["email"] = incoming.get("email")
        elif in_email != ex_email:
            new_candidates.append(incoming.get("email"))

    return ContactMergeResult(fields=fields, new_email_candidates=new_candidates)
