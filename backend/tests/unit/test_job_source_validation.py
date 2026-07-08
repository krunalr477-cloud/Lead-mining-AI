"""Batch-4 P5: reject unknown data-source slugs at job create/estimate time.

The historical frontend sent `public_directories`/`google_jobs` while the enum
has `directories`/`serp_jobs`, so those sources were silently dropped mid-run.
`_validate_sources` now fails loudly on any slug the pipeline can't run.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.jobs import _validate_sources
from app.constants import SourceName


def test_valid_sources_pass():
    _validate_sources([SourceName.GOOGLE_MAPS.value, SourceName.DIRECTORIES.value])
    _validate_sources([s.value for s in SourceName])  # every enum member is valid
    _validate_sources([])  # empty is fine (defaults applied by caller)


@pytest.mark.parametrize(
    "bad",
    [
        ["public_directories"],  # old FE slug for `directories`
        ["google_jobs"],  # old FE slug for `serp_jobs`
        ["google_maps", "totally_made_up"],
    ],
)
def test_unknown_sources_rejected(bad):
    with pytest.raises(HTTPException) as ei:
        _validate_sources(bad)
    assert ei.value.status_code == 422
    assert "Unknown data source" in ei.value.detail
