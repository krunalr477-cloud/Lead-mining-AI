"""Phone extraction + E.164 normalization (spec §9 phones via regex +
``phonenumbers`` normalize, region from company country).

We harvest candidates from ``tel:`` links and a permissive visible-text regex,
then run each through ``phonenumbers`` with the company's country as the default
region so national-format numbers parse. Only numbers ``phonenumbers`` deems
valid are kept, formatted E.164, and de-duplicated.
"""

from __future__ import annotations

import re

import phonenumbers

__all__ = ["COUNTRY_TO_REGION", "extract_phones", "region_for_country"]

# A loose candidate matcher: 7+ digits with the usual separators / extension.
_PHONE_CANDIDATE_RE = re.compile(
    r"(?<![\w.])\+?\(?\d[\d\s().\-]{6,}\d",
)

# Common company-country strings -> ISO region codes for phonenumbers.
COUNTRY_TO_REGION = {
    "india": "IN",
    "in": "IN",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "gb": "GB",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "singapore": "SG",
    "united arab emirates": "AE",
    "uae": "AE",
}


def region_for_country(country: str | None) -> str | None:
    """Map a free-text company country to an ISO-3166 region, or None."""
    if not country:
        return None
    key = country.strip().lower()
    if len(key) == 2:
        return COUNTRY_TO_REGION.get(key, key.upper())
    return COUNTRY_TO_REGION.get(key)


def extract_phones(*, text: str = "", soup=None, country: str | None = None) -> list[str]:
    """Return de-duplicated valid phone numbers in E.164 (best effort).

    ``country`` is the company's country; it seeds the default parse region so
    national-format numbers are accepted. ``tel:`` hrefs are preferred sources.
    """
    region = region_for_country(country)
    candidates: list[str] = []

    if soup is not None:
        for a in soup.select("a[href^=tel], a[href^=TEL]"):
            href = a.get("href", "")
            num = href.split(":", 1)[1] if ":" in href else ""
            if num:
                candidates.append(num)

    if text:
        candidates.extend(_PHONE_CANDIDATE_RE.findall(text))

    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        raw = raw.strip()
        try:
            parsed = phonenumbers.parse(raw, None if raw.startswith("+") else region)
        except phonenumbers.NumberParseException:
            continue
        if not phonenumbers.is_valid_number(parsed):
            continue
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        if e164 not in seen:
            seen.add(e164)
            out.append(e164)
    return out
