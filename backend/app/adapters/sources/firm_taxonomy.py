"""Global firm-type taxonomy + query expansion for lead discovery.

The mining job's ``company_type`` is a free-text field, but users target it with
industry shorthand — "CPA", "KPO", "BPO", "IT", "MSP". Passed verbatim to a
Google Places text search, a bare acronym has poor recall (Places does not
reliably expand "KPO" to "knowledge process outsourcing"). ``expand_company_type``
rewrites known acronyms into search-friendly phrases while keeping the original
token, and passes anything unknown through unchanged — so the field still accepts
"everything".

This is the single source of truth for the firm-type presets; the frontend
combobox mirrors ``FIRM_TYPE_PRESETS`` and ``GET /taxonomy/company-types`` serves
it so the two never drift.
"""

from __future__ import annotations

# Acronym / shorthand -> search-friendly expansion (includes the original token
# so exact-name matches still rank). Keys are matched case-insensitively against
# the whole company_type and against its first word (so "CPA Firm" also hits).
FIRM_TYPE_EXPANSIONS: dict[str, str] = {
    # Accounting & finance
    "ca": "chartered accountant CA firm",
    "ca firm": "chartered accountant CA firm",
    "cpa": "CPA certified public accountant firm",
    "cpa firm": "CPA certified public accountant firm",
    "cfo services": "outsourced CFO financial advisory firm",
    "audit firm": "audit and assurance accounting firm",
    "tax": "tax consultancy accounting firm",
    # Outsourcing family
    "bpo": "BPO business process outsourcing company",
    "kpo": "KPO knowledge process outsourcing company",
    "lpo": "LPO legal process outsourcing company",
    "rpo": "RPO recruitment process outsourcing company",
    "ites": "ITES IT-enabled services company",
    "call center": "call center BPO contact center",
    "contact center": "contact center BPO",
    "shared services": "shared services center GBS",
    # IT & technology
    "it": "IT services technology company",
    "it company": "IT services technology company",
    "it services": "IT services company",
    "msp": "MSP managed IT service provider",
    "managed service provider": "MSP managed IT service provider",
    "saas": "SaaS software company",
    "software": "software development company",
    "software company": "software development company",
    "cloud": "cloud services company",
    "cybersecurity": "cybersecurity firm",
    "ai": "AI artificial intelligence company",
    "data analytics": "data analytics company",
    # Consulting & professional services
    "consulting": "consulting firm",
    "consulting company": "management consulting firm",
    "management consulting": "management consulting firm",
    "strategy consulting": "strategy consulting firm",
    "hr consulting": "HR consulting firm",
    "staffing": "staffing recruitment agency",
    "recruitment agency": "recruitment staffing agency",
    "law firm": "law firm attorneys legal services",
    "legal services": "law firm legal services",
    "engineering firm": "engineering services firm",
    "architecture firm": "architecture design firm",
    # Marketing / agencies
    "agency": "agency",
    "marketing agency": "marketing agency",
    "digital agency": "digital marketing agency",
    "advertising agency": "advertising agency",
    "pr firm": "public relations PR agency",
    # Industry verticals
    "manufacturer": "manufacturing company",
    "hospital": "hospital healthcare provider",
    "healthcare": "healthcare company clinic",
    "hotel": "hotel hospitality",
    "real estate": "real estate agency",
    "logistics": "logistics freight company",
}

# Curated preset list surfaced in the New Mining Job company-type combobox and
# served by the taxonomy endpoint. Grouped for readability; the API flattens it.
FIRM_TYPE_GROUPS: dict[str, list[str]] = {
    "Accounting & Finance": [
        "CA Firm",
        "CPA Firm",
        "Accounting Firm",
        "Audit Firm",
        "Tax Consultancy",
        "Bookkeeping Firm",
        "Financial Advisory",
        "Wealth Management",
    ],
    "IT & Technology": [
        "IT Company",
        "IT Services",
        "Software Company",
        "SaaS Company",
        "Cloud Services",
        "Cybersecurity Firm",
        "AI / Data Analytics",
        "Managed Service Provider (MSP)",
    ],
    "Outsourcing": [
        "BPO",
        "KPO",
        "LPO",
        "RPO",
        "ITES",
        "Call Center",
        "Shared Services",
    ],
    "Consulting & Staffing": [
        "Management Consulting",
        "Strategy Consulting",
        "HR Consulting",
        "Recruitment Agency",
        "Staffing Firm",
        "Business Consulting",
    ],
    "Professional Services": [
        "Law Firm",
        "Legal Services",
        "Engineering Firm",
        "Architecture Firm",
    ],
    "Marketing & Agencies": [
        "Marketing Agency",
        "Digital Agency",
        "Advertising Agency",
        "PR Firm",
    ],
    "Industry": [
        "Manufacturer",
        "Hospital",
        "Healthcare",
        "Hotel",
        "Real Estate",
        "Logistics",
    ],
}

FIRM_TYPE_PRESETS: list[str] = [t for group in FIRM_TYPE_GROUPS.values() for t in group]

# Alternate search phrasings per firm type. One Places textQuery caps at ~60
# results (MAX_PAGES x 20); fanning the same intent across distinct phrasings
# surfaces businesses each single query misses. The first variant used is always
# ``expand_company_type(...)`` (back-compat anchor); these are unioned after it.
FIRM_TYPE_VARIANTS: dict[str, list[str]] = {
    "ca": ["chartered accountant", "CA firm", "tax consultant", "audit firm", "GST consultant"],
    "ca firm": [
        "chartered accountant",
        "CA firm",
        "tax consultant",
        "audit firm",
        "GST consultant",
    ],
    "cpa": ["CPA firm", "certified public accountant", "tax preparation", "accounting firm"],
    "cpa firm": ["CPA firm", "certified public accountant", "tax preparation", "accounting firm"],
    "audit firm": ["audit firm", "assurance services", "chartered accountant"],
    "tax": ["tax consultant", "tax preparation service", "accounting firm"],
    "bpo": ["BPO company", "business process outsourcing", "call center services"],
    "kpo": ["KPO company", "knowledge process outsourcing", "research outsourcing"],
    "it": ["IT services company", "software company", "technology consulting"],
    "it company": ["IT services company", "software company", "technology consulting"],
    "it services": ["IT services company", "software development", "technology consulting"],
    "msp": ["managed IT service provider", "IT support company", "IT services"],
    "software": ["software development company", "software agency", "IT services"],
    "software company": ["software development company", "software agency", "IT services"],
    "law firm": ["law firm", "advocates", "legal services", "attorneys"],
    "legal services": ["legal services", "law firm", "advocates"],
    "marketing agency": ["marketing agency", "digital marketing agency", "branding agency"],
    "digital agency": ["digital marketing agency", "web design agency", "SEO agency"],
    "recruitment agency": ["recruitment agency", "staffing agency", "placement services"],
    "staffing": ["staffing agency", "recruitment agency", "manpower services"],
    "real estate": ["real estate agency", "property dealer", "realtor"],
    "consulting": ["consulting firm", "business consultant", "advisory services"],
}


def expand_query_variants(company_type: str | None, limit: int) -> list[str]:
    """Distinct search phrasings for a firm type, capped at ``limit``.

    The first element is always ``expand_company_type(company_type)`` so a
    single-variant configuration behaves exactly like the legacy single query.
    Unknown types return just that one element.
    """
    limit = max(1, limit)
    anchor = expand_company_type(company_type)
    out: list[str] = [anchor] if anchor else []
    seen = {anchor.lower()} if anchor else set()
    key = _normalize(company_type or "")
    variants = FIRM_TYPE_VARIANTS.get(key)
    if variants is None:
        first = key.split(" ", 1)[0]
        variants = FIRM_TYPE_VARIANTS.get(first, [])
    for phrase in variants:
        low = phrase.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(phrase)
        if len(out) >= limit:
            break
    return out[:limit] or ["companies"]


def _normalize(value: str) -> str:
    # Strip a trailing "(MSP)"-style parenthetical and lowercase.
    base = value.split("(")[0].strip().lower()
    return " ".join(base.split())


def expand_company_type(company_type: str | None) -> str:
    """Rewrite firm shorthand into a search-friendly phrase for text search.

    Unknown values pass through unchanged so any company type is still targetable.
    Matching tries the full normalized string first, then its first word (so both
    "CPA" and "CPA Firm" expand), otherwise returns the original input verbatim.
    """
    if not company_type or not company_type.strip():
        return ""
    key = _normalize(company_type)
    if key in FIRM_TYPE_EXPANSIONS:
        return FIRM_TYPE_EXPANSIONS[key]
    # A parenthetical acronym, e.g. "Managed Service Provider (MSP)" -> "msp".
    if "(" in company_type and ")" in company_type:
        acronym = (
            company_type[company_type.index("(") + 1 : company_type.index(")")].strip().lower()
        )
        if acronym in FIRM_TYPE_EXPANSIONS:
            return FIRM_TYPE_EXPANSIONS[acronym]
    first = key.split(" ", 1)[0]
    if first in FIRM_TYPE_EXPANSIONS:
        return FIRM_TYPE_EXPANSIONS[first]
    return company_type.strip()
