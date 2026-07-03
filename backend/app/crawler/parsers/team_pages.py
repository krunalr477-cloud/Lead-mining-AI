"""Team / leadership page extraction (spec §9 "Team page pattern extraction",
"Role/designation keyword matching").

Real team pages render people as repeated "cards": a small block holding a
person's name and their designation. We detect the dominant repeated container,
then within each card pair a human name (Title-Case tokens) with a line that
contains a designation keyword. Each pairing yields (name, designation,
seniority, role_category, confidence). Confidence rises with a clean two-part
name, an exact role keyword, and a recognized decision-maker title.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

__all__ = ["TeamMember", "DESIGNATION_KEYWORDS", "extract_team_members", "classify_designation"]

# (keyword, seniority, role_category) — order matters: first match wins.
DESIGNATION_KEYWORDS: list[tuple[str, str, str]] = [
    ("founder", "c_level", "founder"),
    ("co-founder", "c_level", "founder"),
    ("cofounder", "c_level", "founder"),
    ("chief executive", "c_level", "executive"),
    ("ceo", "c_level", "executive"),
    ("managing partner", "c_level", "partner"),
    ("managing director", "c_level", "executive"),
    ("cto", "c_level", "executive"),
    ("cfo", "c_level", "finance"),
    ("coo", "c_level", "operations"),
    ("chief", "c_level", "executive"),
    ("owner", "owner", "owner"),
    ("principal", "senior", "principal"),
    ("partner", "senior", "partner"),
    ("vice president", "senior", "sales"),
    ("vp ", "senior", "sales"),
    ("director", "senior", "director"),
    ("head of ", "senior", "department_head"),
    ("president", "c_level", "executive"),
    ("manager", "mid", "manager"),
    ("lead", "mid", "lead"),
    ("associate", "junior", "associate"),
    ("consultant", "mid", "consultant"),
    ("advisor", "senior", "advisor"),
]

# A person name: 2-4 Title-Case tokens, allowing initials / apostrophes / hyphens.
_NAME_RE = re.compile(
    r"\b([A-Z][a-z'’\-]+(?:\s+(?:[A-Z]\.?|[A-Z][a-z'’\-]+)){1,3})\b",
)


@dataclass(slots=True)
class TeamMember:
    name: str
    designation: str
    seniority: str
    role_category: str
    confidence: float
    snippet: str


def _keyword_hit(keyword: str, low: str) -> bool:
    """Substring match, but word-bounded for short/acronym keywords so ``cto``
    does not match ``direCTOr`` and ``vp`` does not match ``deVeloPment``."""
    if keyword.strip().isalpha() and len(keyword.strip()) <= 4:
        return re.search(rf"\b{re.escape(keyword.strip())}\b", low) is not None
    return keyword in low


def classify_designation(text: str) -> tuple[str, str] | None:
    """Return (seniority, role_category) if ``text`` names a business role."""
    low = text.lower()
    for keyword, seniority, role_cat in DESIGNATION_KEYWORDS:
        if _keyword_hit(keyword, low):
            return seniority, role_cat
    return None


def _looks_like_name(text: str) -> str | None:
    text = text.strip()
    # Reject lines that are clearly designations, not names.
    if classify_designation(text) is not None and len(text.split()) <= 3:
        return None
    m = _NAME_RE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    # Guard against ALL-CAPS headings or single tokens.
    parts = name.split()
    if len(parts) < 2:
        return None
    return name


def _candidate_containers(soup):
    """Find the repeated element class that most looks like a people grid."""
    counter: Counter[str] = Counter()
    for el in soup.find_all(True):
        classes = el.get("class") or []
        for cls in classes:
            low = cls.lower()
            if any(
                tok in low
                for tok in (
                    "team",
                    "member",
                    "person",
                    "card",
                    "staff",
                    "people",
                    "profile",
                    "leader",
                )
            ):
                counter[cls] += 1
    # Prefer a class that repeats (a grid), else fall back to any match.
    for cls, count in counter.most_common():
        if count >= 2:
            return soup.find_all(class_=cls)
    if counter:
        cls = counter.most_common(1)[0][0]
        return soup.find_all(class_=cls)
    return []


def extract_team_members(soup) -> list[TeamMember]:
    """Extract (name, designation) pairs from repeated team cards."""
    members: list[TeamMember] = []
    seen: set[str] = set()

    for card in _candidate_containers(soup):
        # Line-oriented text so we can pair name-line with role-line.
        lines = [ln.strip() for ln in card.get_text("\n").split("\n") if ln.strip()]
        if not lines:
            continue

        name: str | None = None
        designation: str | None = None
        role: tuple[str, str] | None = None
        for line in lines:
            if name is None:
                cand = _looks_like_name(line)
                if cand:
                    name = cand
                    continue
            if designation is None:
                cls = classify_designation(line)
                if cls is not None:
                    designation = line
                    role = cls
        if not name or not designation or role is None:
            continue

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        seniority, role_cat = role
        # Confidence: base, +clean 2-part name, +decision-maker seniority.
        conf = 0.55
        if 2 <= len(name.split()) <= 3:
            conf += 0.15
        if seniority in ("c_level", "owner", "senior"):
            conf += 0.15
        if len(designation) <= 60:
            conf += 0.05
        members.append(
            TeamMember(
                name=name,
                designation=designation,
                seniority=seniority,
                role_category=role_cat,
                confidence=round(min(conf, 0.95), 3),
                snippet=" — ".join([name, designation])[:200],
            )
        )
    return members
