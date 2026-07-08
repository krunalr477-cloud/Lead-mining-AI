"""Batch-3 sheet-output quality gates (spec §S).

Covers the defects seen in the first exported workbook: counts rendered as
floats ("14.0"), blank industry column, and README never populated.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.adapters.sources.google_maps import _industry_from_place
from app.sheetsync.tabs import scalarize


@pytest.mark.parametrize(
    "value, expected",
    [
        (Decimal("14"), 14),  # whole -> int, not 14.0
        (Decimal("20.0"), 20),  # trailing-zero fractional is still integral
        (Decimal("0"), 0),
        (Decimal("4.6"), 4.6),  # true fractional stays float
        (Decimal("3.50"), 3.5),
    ],
)
def test_scalarize_preserves_integers(value, expected):
    out = scalarize(value)
    assert out == expected
    assert type(out) is type(expected)  # int stays int, float stays float


@pytest.mark.parametrize(
    "place, expected",
    [
        # localized display name wins
        ({"primaryTypeDisplayName": {"text": "Accounting Firm"}, "primaryType": "accounting"},
         "Accounting Firm"),
        # fall back to humanized slug
        ({"primaryType": "cpa_office"}, "Cpa Office"),
        ({"primaryType": "accounting"}, "Accounting"),
        # nothing available
        ({}, None),
        ({"primaryTypeDisplayName": {"text": ""}, "primaryType": ""}, None),
    ],
)
def test_industry_from_place(place, expected):
    assert _industry_from_place(place) == expected
