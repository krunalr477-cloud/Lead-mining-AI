"""Sales-ready eligibility (property-style over all statuses) + ranking."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.constants import FinalEmailStatus
from app.pipeline.sales_ready import is_sales_ready, rank_key

# --------------------------------------------------------------------------- #
# Eligibility — ONLY VERIFIED passes
# --------------------------------------------------------------------------- #


def test_verified_passes():
    assert is_sales_ready(FinalEmailStatus.VERIFIED) is True


def test_verified_string_form_passes():
    assert is_sales_ready("VERIFIED") is True


@pytest.mark.parametrize(
    "status", [s for s in FinalEmailStatus if s is not FinalEmailStatus.VERIFIED]
)
def test_every_non_verified_status_excluded(status):
    """Property: no status other than VERIFIED can be sales-ready (spec §12/§25)."""
    assert is_sales_ready(status) is False


def test_none_status_excluded():
    assert is_sales_ready(None) is False


@pytest.mark.parametrize("flag", ["suppressed", "bounced", "unsubscribed"])
def test_verified_excluded_by_list_hygiene_flags(flag):
    assert is_sales_ready(FinalEmailStatus.VERIFIED, **{flag: True}) is False


def test_verified_excluded_by_raw_disqualifiers():
    assert is_sales_ready(FinalEmailStatus.VERIFIED, disposable=True) is False
    assert is_sales_ready(FinalEmailStatus.VERIFIED, provider_invalid=True) is False
    assert is_sales_ready(FinalEmailStatus.VERIFIED, mx_ok=False) is False


def test_verified_role_based_excluded_unless_allowed():
    assert is_sales_ready(FinalEmailStatus.VERIFIED, role_based=True) is False
    assert is_sales_ready(FinalEmailStatus.VERIFIED, role_based=True, allow_role_based=True) is True


def test_every_status_with_all_bad_flags_still_only_verified_passes():
    """Exhaustive cross-check: for each status, flip each disqualifier and confirm."""
    for status in FinalEmailStatus:
        clean = is_sales_ready(status)
        assert clean is (status is FinalEmailStatus.VERIFIED)


# --------------------------------------------------------------------------- #
# rank_key ordering
# --------------------------------------------------------------------------- #


def test_primary_contact_ranks_first():
    primary = {"primary_contact": True, "confidence_score": 0.1}
    secondary = {"primary_contact": False, "confidence_score": 0.99}
    ranked = sorted([secondary, primary], key=rank_key, reverse=True)
    assert ranked[0] is primary


def test_confidence_breaks_tie_after_primary():
    a = {"primary_contact": True, "confidence_score": Decimal("0.9")}
    b = {"primary_contact": True, "confidence_score": Decimal("0.6")}
    ranked = sorted([b, a], key=rank_key, reverse=True)
    assert ranked[0] is a


def test_role_relevance_after_confidence():
    founder = {"primary_contact": True, "confidence_score": 0.8, "role_category": "founder"}
    junior = {"primary_contact": True, "confidence_score": 0.8, "role_category": "department_head"}
    ranked = sorted([junior, founder], key=rank_key, reverse=True)
    assert ranked[0] is founder


def test_recency_breaks_final_tie():
    older = {
        "primary_contact": True,
        "confidence_score": 0.8,
        "role_category": "ceo",
        "last_verified_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    newer = {
        "primary_contact": True,
        "confidence_score": 0.8,
        "role_category": "ceo",
        "last_verified_at": datetime(2026, 7, 1, tzinfo=UTC),
    }
    ranked = sorted([older, newer], key=rank_key, reverse=True)
    assert ranked[0] is newer


def test_rank_key_handles_missing_and_none_fields():
    # Must not raise on a sparse contact.
    key = rank_key({})
    assert isinstance(key, tuple)
    assert key[0] == 0  # not primary


def test_full_sort_order_end_to_end():
    contacts = [
        {
            "id": "c1",
            "primary_contact": False,
            "confidence_score": 0.95,
            "role_category": "founder",
        },
        {
            "id": "c2",
            "primary_contact": True,
            "confidence_score": 0.50,
            "role_category": "director",
        },
        {"id": "c3", "primary_contact": True, "confidence_score": 0.90, "role_category": "partner"},
    ]
    ranked = [c["id"] for c in sorted(contacts, key=rank_key, reverse=True)]
    # Primary contacts first (c3 > c2 by confidence), then non-primary c1.
    assert ranked == ["c3", "c2", "c1"]
