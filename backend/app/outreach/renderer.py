"""Strict ``{{Variable}}`` template renderer (spec §13). Pure, no I/O.

Only the whitelisted :data:`~app.constants.TEMPLATE_VARIABLES` may appear. The
renderer is **strict**: an unknown variable, or a known variable with no value
for the recipient, raises :class:`TemplateRenderError` so the message fails
validation instead of ever putting a literal ``{{X}}`` on the wire.

``build_context(...)`` assembles the variable map from a recipient's contact +
company + lead facts; ``render(template, context)`` substitutes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.constants import TEMPLATE_VARIABLES

__all__ = [
    "TemplateRenderError",
    "build_context",
    "render",
    "used_variables",
]

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_ALLOWED = set(TEMPLATE_VARIABLES)


class TemplateRenderError(ValueError):
    """A template referenced an unknown or unresolved variable."""


def used_variables(template: str) -> list[str]:
    """Every ``{{Var}}`` name referenced in ``template`` (in order, de-duped)."""
    seen: dict[str, None] = {}
    for m in _VAR_RE.finditer(template):
        seen.setdefault(m.group(1), None)
    return list(seen)


@dataclass(slots=True)
class RecipientFacts:
    """Flat facts about one recipient, used to build the variable context."""

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    company: str | None = None
    industry: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    services: str | None = None
    designation: str | None = None
    website: str | None = None
    hiring_signal: str | None = None


def build_context(facts: RecipientFacts) -> dict[str, str]:
    """Map :class:`RecipientFacts` to the ``{{Variable}}`` name -> value dict.

    Missing values are represented as ``None`` (not ""), so the strict renderer
    can distinguish "template didn't use it" from "used it but we have nothing".
    """
    full = facts.full_name or " ".join(p for p in (facts.first_name, facts.last_name) if p) or None
    return {
        "FirstName": facts.first_name,
        "LastName": facts.last_name,
        "FullName": full,
        "Company": facts.company,
        "Industry": facts.industry,
        "City": facts.city,
        "State": facts.state,
        "Country": facts.country,
        "Services": facts.services,
        "Designation": facts.designation,
        "Website": facts.website,
        "HiringSignal": facts.hiring_signal,
    }


def render(template: str, context: dict[str, str | None]) -> str:
    """Substitute every ``{{Var}}`` in ``template`` from ``context`` (strict).

    Raises :class:`TemplateRenderError` when a referenced variable is not a
    known template variable, or resolves to ``None``/empty — guaranteeing a
    literal ``{{X}}`` never reaches the recipient.
    """
    unknown = [name for name in used_variables(template) if name not in _ALLOWED]
    if unknown:
        raise TemplateRenderError(
            f"Unknown template variable(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(TEMPLATE_VARIABLES)}"
        )

    missing: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        value = context.get(name)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(name)
            return ""
        return str(value)

    result = _VAR_RE.sub(_sub, template)
    if missing:
        raise TemplateRenderError(
            f"No value for template variable(s): {', '.join(sorted(set(missing)))}"
        )
    return result
