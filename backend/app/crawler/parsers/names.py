"""Person-name plausibility + derivation (spec §9 contact quality).

Real crawls scoop up template/boilerplate JSON-LD nodes ("Template"), UI text
("Learn More"), and marketing/service phrases ("Outsourced Controller Services")
and — with no gate — persist them as *people*. ``is_plausible_person_name``
rejects those; ``derive_name_from_local`` recovers a real name from a
``first.last@`` email local part so person emails don't land nameless.
"""

from __future__ import annotations

import re

__all__ = ["is_plausible_person_name", "derive_name_from_local"]

# Tokens that never appear in a real personal name but dominate the junk the
# crawler mis-parsed as people: navigation/marketing UI words, business/service
# nouns (firm names, service lines), and CMS placeholder words.
_NON_NAME_TOKENS: frozenset[str] = frozenset(
    {
        # nav / UI / marketing
        "learn",
        "more",
        "read",
        "view",
        "all",
        "get",
        "started",
        "start",
        "contact",
        "about",
        "home",
        "our",
        "us",
        "we",
        "team",
        "click",
        "here",
        "menu",
        "search",
        "login",
        "log",
        "sign",
        "submit",
        "send",
        "subscribe",
        "download",
        "free",
        "quote",
        "now",
        "today",
        "welcome",
        "privacy",
        "policy",
        "terms",
        "cookie",
        "cookies",
        "copyright",
        "rights",
        "reserved",
        "page",
        "next",
        "previous",
        "back",
        "close",
        "open",
        "toggle",
        "skip",
        "content",
        "main",
        # business / service nouns (firm names, service lines)
        "accounting",
        "bookkeeping",
        "tax",
        "taxes",
        "audit",
        "auditing",
        "assurance",
        "advisory",
        "consulting",
        "consultancy",
        "planning",
        "solutions",
        "solution",
        "services",
        "service",
        "outsourced",
        "controller",
        "cfo",
        "payroll",
        "wealth",
        "financial",
        "finance",
        "compliance",
        "corporate",
        "business",
        "firm",
        "company",
        "group",
        "associates",
        "cpa",
        "cpas",
        "llc",
        "llp",
        "inc",
        "pllc",
        "pc",
        "pa",
        "practice",
        "office",
        "offices",
        "department",
        "traditional",
        # placeholder / template
        "template",
        "boilerplate",
        "placeholder",
        "lorem",
        "ipsum",
        "example",
        "sample",
        "demo",
        "untitled",
        "undefined",
        "null",
        "none",
        "test",
    }
)

# A token in a real name: alphabetic (allowing internal hyphen / apostrophe) or a
# 1-2 letter initial optionally followed by a dot ("M.", "A", "J.R.").
_NAME_TOKEN_RE = re.compile(r"^(?:[A-Z]\.?){1,2}$|^[A-Z][a-z’'A-Za-z\-]*$")
_MAX_NAME_LEN = 60


def is_plausible_person_name(name: str | None) -> bool:
    """True if ``name`` looks like a real person's name (2-4 title-case tokens,
    all alphabetic, none a UI/marketing/service/placeholder word)."""
    if not name:
        return False
    name = name.strip()
    if not name or len(name) > _MAX_NAME_LEN:
        return False
    tokens = name.split()
    if not (2 <= len(tokens) <= 4):
        return False
    for tok in tokens:
        if not _NAME_TOKEN_RE.match(tok):
            return False
        core = tok.replace(".", "").replace("-", "").replace("’", "").replace("'", "").lower()
        if core in _NON_NAME_TOKENS:
            return False
    return True


def derive_name_from_local(local: str) -> tuple[str, str, str] | None:
    """Recover ``(full, first, last)`` from a ``first.last`` / ``first_last`` email
    local part. Returns None for single-token / generic locals (info, sales, ...)."""
    if not local:
        return None
    for sep in (".", "_", "-"):
        if sep in local:
            parts = [p for p in local.split(sep) if p.isalpha() and len(p) >= 2]
            if len(parts) == 2:
                first, last = parts[0].capitalize(), parts[1].capitalize()
                full = f"{first} {last}"
                if is_plausible_person_name(full):
                    return full, first, last
            return None
    return None
