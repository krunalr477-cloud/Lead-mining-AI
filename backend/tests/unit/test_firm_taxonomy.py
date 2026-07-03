"""Firm-type query expansion (global firm targeting: CPA/IT/KPO/BPO/...)."""

import pytest

from app.adapters.base import JobSpec
from app.adapters.sources.firm_taxonomy import (
    FIRM_TYPE_PRESETS,
    expand_company_type,
)
from app.adapters.sources.google_maps import _text_query


@pytest.mark.parametrize(
    "raw, must_contain",
    [
        ("CPA", "certified public accountant"),
        ("CPA Firm", "certified public accountant"),
        ("KPO", "knowledge process outsourcing"),
        ("BPO", "business process outsourcing"),
        ("LPO", "legal process outsourcing"),
        ("RPO", "recruitment process outsourcing"),
        ("IT", "IT services"),
        ("IT Company", "IT services"),
        ("MSP", "managed IT"),
        ("Managed Service Provider (MSP)", "managed IT"),
        ("ITES", "IT-enabled services"),
        ("SaaS Company", "software"),
        ("CA Firm", "chartered accountant"),
    ],
)
def test_known_shorthand_expands(raw: str, must_contain: str) -> None:
    expanded = expand_company_type(raw).lower()
    assert must_contain.lower() in expanded
    # The original token stays present so exact-name matches still rank.
    assert raw.split("(")[0].strip().split()[0].lower() in expanded


def test_unknown_type_passes_through() -> None:
    # "everything" — any firm type is still targetable, unchanged.
    assert expand_company_type("Boutique Winery") == "Boutique Winery"
    assert expand_company_type("Yacht Broker") == "Yacht Broker"


def test_blank_is_empty() -> None:
    assert expand_company_type(None) == ""
    assert expand_company_type("   ") == ""


def test_presets_are_nonempty_and_include_global_firms() -> None:
    for needle in ["CPA Firm", "IT Company", "KPO", "BPO", "Managed Service Provider (MSP)"]:
        assert needle in FIRM_TYPE_PRESETS


def test_text_query_uses_expansion() -> None:
    job = JobSpec(
        job_id=__import__("uuid").uuid4(),
        tenant_id=__import__("uuid").uuid4(),
        company_type="KPO",
        services=["Analytics"],
        country="India",
        state="Karnataka",
        city="Bengaluru",
        zipcode=None,
        latitude=None,
        longitude=None,
        radius_km=25.0,
        company_size_min=None,
        company_size_max=None,
        contact_roles=[],
        exclude_keywords=[],
    )
    q = _text_query(job).lower()
    assert "knowledge process outsourcing" in q
    assert "bengaluru" in q
    assert "analytics" in q
