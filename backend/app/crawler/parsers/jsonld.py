"""JSON-LD / schema.org extraction (spec §8 "Parse JSON-LD, schema.org").

Tolerant of the shapes real sites emit: a single object, an array of objects,
an ``@graph`` wrapper, ``@type`` as a string or a list, and values that are
either scalars or nested objects. We pull business fields (name, phones, emails,
address, sameAs social links, description) from Organization / LocalBusiness /
ContactPoint, people from Person, and job postings from JobPosting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["JsonLdResult", "JsonLdPerson", "JsonLdJob", "parse_jsonld"]


@dataclass(slots=True)
class JsonLdPerson:
    name: str | None = None
    job_title: str | None = None
    email: str | None = None
    telephone: str | None = None
    same_as: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JsonLdJob:
    title: str | None = None
    description: str | None = None
    date_posted: datetime | None = None
    location: str | None = None
    url: str | None = None


@dataclass(slots=True)
class JsonLdResult:
    name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    same_as: list[str] = field(default_factory=list)
    description: str | None = None
    address: str | None = None
    people: list[JsonLdPerson] = field(default_factory=list)
    jobs: list[JsonLdJob] = field(default_factory=list)


_ORG_TYPES = {"organization", "localbusiness", "corporation", "professionalservice"}


def _types(node: dict) -> set[str]:
    raw = node.get("@type")
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(t).lower() for t in raw}
    return {str(raw).lower()}


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _scalar(value) -> str | None:
    """Coerce a scalar-or-nested-object value to a display string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "@value", "value"):
            if key in value:
                return _scalar(value[key])
    if isinstance(value, list) and value:
        return _scalar(value[0])
    return None


def _address(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list) and value:
        return _address(value[0])
    if isinstance(value, dict):
        parts = [
            _scalar(value.get(k))
            for k in (
                "streetAddress",
                "addressLocality",
                "addressRegion",
                "postalCode",
                "addressCountry",
            )
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    return None


def _parse_date(value) -> datetime | None:
    text = _scalar(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_nodes(data):
    """Yield every dict node from arbitrary JSON-LD (arrays, @graph, nesting)."""
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            yield item
            if "@graph" in item:
                stack.extend(_as_list(item["@graph"]))


def _collect_contact_points(node: dict, result: JsonLdResult) -> None:
    for cp in _as_list(node.get("contactPoint")) + _as_list(node.get("contactPoints")):
        if not isinstance(cp, dict):
            continue
        for phone in _as_list(cp.get("telephone")):
            s = _scalar(phone)
            if s and s not in result.phones:
                result.phones.append(s)
        for email in _as_list(cp.get("email")):
            s = _scalar(email)
            if s and s not in result.emails:
                result.emails.append(s.lower())


def parse_jsonld(blocks: list[str]) -> JsonLdResult:
    """Parse a list of raw ``<script type=application/ld+json>`` bodies."""
    result = JsonLdResult()
    for raw in blocks:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        for node in _iter_nodes(data):
            types = _types(node)

            if types & _ORG_TYPES:
                if result.name is None:
                    result.name = _scalar(node.get("name"))
                for phone in _as_list(node.get("telephone")):
                    s = _scalar(phone)
                    if s and s not in result.phones:
                        result.phones.append(s)
                for email in _as_list(node.get("email")):
                    s = _scalar(email)
                    if s and s.lower() not in result.emails:
                        result.emails.append(s.lower())
                for link in _as_list(node.get("sameAs")):
                    s = _scalar(link)
                    if s and s not in result.same_as:
                        result.same_as.append(s)
                if result.description is None:
                    result.description = _scalar(node.get("description"))
                if result.address is None:
                    result.address = _address(node.get("address"))
                _collect_contact_points(node, result)

            if "person" in types:
                person = JsonLdPerson(
                    name=_scalar(node.get("name")),
                    job_title=_scalar(node.get("jobTitle")),
                    email=(_scalar(node.get("email")) or "").lower() or None,
                    telephone=_scalar(node.get("telephone")),
                    same_as=[s for s in (_scalar(x) for x in _as_list(node.get("sameAs"))) if s],
                )
                if person.name:
                    result.people.append(person)

            if "jobposting" in types:
                loc = node.get("jobLocation")
                loc_str = None
                if isinstance(loc, dict):
                    loc_str = _address(loc.get("address")) or _scalar(loc.get("name"))
                else:
                    loc_str = _scalar(loc)
                result.jobs.append(
                    JsonLdJob(
                        title=_scalar(node.get("title")),
                        description=_scalar(node.get("description")),
                        date_posted=_parse_date(node.get("datePosted")),
                        location=loc_str,
                        url=_scalar(node.get("url")),
                    )
                )

    return result
