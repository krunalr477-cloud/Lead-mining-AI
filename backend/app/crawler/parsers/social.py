"""Social link + hiring-signal detection (spec §8 social links, hiring signals;
§9 LinkedIn/Facebook business links only).

``extract_social_links`` collects LinkedIn company/personal and Facebook page
links from anchors and JSON-LD ``sameAs`` values, classifying each. We keep only
*business/contact* links (linkedin.com/company or /in, facebook.com pages) and
never private-profile scraping targets.

``detect_hiring_signals`` scans visible text for hiring phrases ("we're hiring",
"join our team", "open positions", ...) and returns matched phrase + snippet so
the adapter can mint an ``ExtractedHiringSignal``.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

__all__ = [
    "HIRING_PHRASES",
    "classify_social",
    "detect_hiring_signals",
    "extract_social_links",
]

_LINKEDIN_COMPANY_RE = re.compile(r"linkedin\.com/(company|school)/", re.IGNORECASE)
_LINKEDIN_PERSON_RE = re.compile(r"linkedin\.com/in/", re.IGNORECASE)
_FACEBOOK_RE = re.compile(r"facebook\.com/", re.IGNORECASE)
# Facebook non-page paths we must not treat as a business page.
_FB_NONPAGE = ("sharer", "share.php", "dialog", "plugins", "tr?", "login", "profile.php")

HIRING_PHRASES = [
    "we're hiring",
    "we are hiring",
    "join our team",
    "open positions",
    "open roles",
    "current openings",
    "career opportunities",
    "now hiring",
    "job openings",
    "we're looking for",
    "we are looking for",
]


def classify_social(url: str) -> str | None:
    """Return 'linkedin' / 'linkedin_person' / 'facebook' for a business link."""
    if not url:
        return None
    low = url.strip()
    if _LINKEDIN_COMPANY_RE.search(low):
        return "linkedin"
    if _LINKEDIN_PERSON_RE.search(low):
        return "linkedin_person"
    if _FACEBOOK_RE.search(low):
        host_path = low.lower()
        if any(bad in host_path for bad in _FB_NONPAGE):
            return None
        # Must have a page slug after the host.
        path = urlparse(low if "//" in low else "https://" + low).path.strip("/")
        if path:
            return "facebook"
    return None


def extract_social_links(*, soup=None, extra_urls: list[str] | None = None) -> dict[str, str]:
    """Collect business social links keyed by network.

    First match per network wins (company links preferred over personal for the
    canonical 'linkedin' slot). Personal linkedin.com/in links are returned under
    'linkedin_person' only if no company link is present.
    """
    company_ln: str | None = None
    person_ln: str | None = None
    facebook: str | None = None

    urls: list[str] = list(extra_urls or [])
    if soup is not None:
        for a in soup.find_all("a", href=True):
            urls.append(a["href"])

    for url in urls:
        kind = classify_social(url)
        if kind == "linkedin" and company_ln is None:
            company_ln = url
        elif kind == "linkedin_person" and person_ln is None:
            person_ln = url
        elif kind == "facebook" and facebook is None:
            facebook = url

    out: dict[str, str] = {}
    if company_ln:
        out["linkedin"] = company_ln
    elif person_ln:
        out["linkedin"] = person_ln
    if facebook:
        out["facebook"] = facebook
    return out


def detect_hiring_signals(text: str) -> list[tuple[str, str]]:
    """Return (matched_phrase, surrounding_snippet) for each hiring phrase hit."""
    if not text:
        return []
    low = text.lower()
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for phrase in HIRING_PHRASES:
        idx = low.find(phrase)
        if idx == -1 or phrase in seen:
            continue
        seen.add(phrase)
        start = max(0, idx - 40)
        end = min(len(text), idx + len(phrase) + 60)
        snippet = " ".join(text[start:end].split())
        hits.append((phrase, snippet))
    return hits
