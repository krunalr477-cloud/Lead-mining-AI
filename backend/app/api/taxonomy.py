"""Taxonomy endpoint — firm-type presets for the New Mining Job company picker.

Single source of truth so the frontend combobox and the discovery query-expansion
never drift. Public within the app (auth-gated) and cheap/static.
"""

from fastapi import APIRouter

from app.adapters.sources.firm_taxonomy import FIRM_TYPE_GROUPS, FIRM_TYPE_PRESETS
from app.deps import CurrentUser

router = APIRouter(tags=["taxonomy"])


@router.get("/taxonomy/company-types")
async def company_types(_: CurrentUser) -> dict[str, object]:
    """Grouped + flattened global firm-type presets (CA/CPA, IT, KPO, BPO, ...)."""
    return {
        "groups": [
            {"label": label, "options": options} for label, options in FIRM_TYPE_GROUPS.items()
        ],
        "presets": FIRM_TYPE_PRESETS,
    }
