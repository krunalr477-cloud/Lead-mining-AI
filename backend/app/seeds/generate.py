"""Deterministic seed-corpus generator for the mock adapters (spec §8, §21).

Run once to (re)generate the JSON corpora under app/seeds/data/. The output is a
function of a fixed integer seed only, so the committed JSON is reproducible and
the runtime never regenerates it. Mock adapters read these corpora and layer
per-job/per-company jitter on top (see app.adapters.mock.rng).

    uv run python -m app.seeds.generate           # regenerate + write
    uv run python -m app.seeds.generate --check    # verify committed == fresh

The demo scenario (spec §21): CA firms in Ahmedabad, ~248 companies, ~611
contacts, 73% emails, targeting Founder/CEO/Managing Partner/Director/Partner.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED = 20260703  # frozen — bump only to intentionally re-cut every corpus

# Ahmedabad geography (spec §21: 20km radius of city centre).
AHMEDABAD_CENTER = (23.0225, 72.5714)
RADIUS_KM = 20.0

# (locality, pincode) — real Ahmedabad localities and their PIN codes.
LOCALITIES = [
    ("Navrangpura", "380009"),
    ("C G Road", "380009"),
    ("Ashram Road", "380009"),
    ("Ellisbridge", "380006"),
    ("Paldi", "380007"),
    ("Vasna", "380007"),
    ("Satellite", "380015"),
    ("Prahlad Nagar", "380015"),
    ("Vastrapur", "380015"),
    ("Bodakdev", "380054"),
    ("Thaltej", "380059"),
    ("S G Highway", "380054"),
    ("Bopal", "380058"),
    ("Gota", "382481"),
    ("Chandkheda", "382424"),
    ("Naranpura", "380013"),
    ("Vadaj", "380013"),
    ("Sabarmati", "380005"),
    ("Maninagar", "380008"),
    ("Isanpur", "382443"),
    ("Vatva", "382445"),
    ("Ghatlodia", "380061"),
    ("Nikol", "382350"),
    ("Naroda", "382330"),
    ("Ramdev Nagar", "380015"),
    ("Jodhpur", "380015"),
    ("Ambawadi", "380006"),
    ("Shahibaug", "380004"),
    ("Vejalpur", "380051"),
    ("Makarba", "380051"),
]

# CA / audit-firm naming corpus (plausible Ahmedabad Gujarati/Indian surnames).
SURNAMES = [
    "Shah",
    "Patel",
    "Mehta",
    "Desai",
    "Trivedi",
    "Joshi",
    "Parikh",
    "Modi",
    "Vyas",
    "Bhatt",
    "Dave",
    "Thakkar",
    "Amin",
    "Gandhi",
    "Kothari",
    "Sheth",
    "Nanavati",
    "Munshi",
    "Zaveri",
    "Doshi",
    "Panchal",
    "Rana",
    "Chokshi",
    "Vora",
    "Jhaveri",
    "Pandya",
    "Raval",
    "Soni",
    "Contractor",
    "Majmudar",
]
FIRST_NAMES_M = [
    "Rajesh",
    "Amit",
    "Nikhil",
    "Bhavesh",
    "Kalpesh",
    "Jignesh",
    "Mihir",
    "Paresh",
    "Chirag",
    "Hardik",
    "Ketan",
    "Sanjay",
    "Manish",
    "Tushar",
    "Viral",
    "Dhaval",
    "Bhargav",
    "Rushabh",
    "Kunal",
    "Parth",
    "Harsh",
    "Vishal",
    "Nirav",
    "Ronak",
    "Devang",
    "Ashish",
    "Maulik",
    "Hemant",
]
FIRST_NAMES_F = [
    "Priya",
    "Nisha",
    "Rina",
    "Kruti",
    "Foram",
    "Hetal",
    "Bhoomi",
    "Payal",
    "Krupa",
    "Shivani",
    "Riddhi",
    "Dhara",
    "Avni",
    "Jinal",
    "Khushbu",
    "Pooja",
    "Manisha",
    "Sneha",
    "Trupti",
    "Vaidehi",
]

FIRM_SUFFIXES = [
    "& Associates",
    "& Co.",
    "& Co. LLP",
    "Associates",
    "Consultants",
    "Advisors",
    "& Company",
    "LLP",
    "& Partners",
]
FIRM_PREFIXES = ["", "", "", "M/s ", "", ""]  # mostly none

DESIGNATIONS = [
    ("Founder", "founder", "executive", "Founder"),
    ("Managing Partner", "partner", "executive", "Partner"),
    ("Partner", "partner", "senior", "Partner"),
    ("CEO", "ceo", "executive", "Executive"),
    ("Managing Director", "director", "executive", "Director"),
    ("Director", "director", "senior", "Director"),
    ("Principal", "principal", "senior", "Principal"),
    ("Senior Partner", "partner", "executive", "Partner"),
    ("Audit Partner", "partner", "senior", "Audit"),
    ("Tax Partner", "partner", "senior", "Tax"),
]

# Role inboxes to exercise stage-3 role-based rejection (spec §11.3).
ROLE_INBOXES = ["info", "contact", "admin", "office", "ca"]

SERVICES_POOL = [
    "Audit",
    "Tax Filing",
    "GST",
    "Statutory Audit",
    "Internal Audit",
    "Income Tax",
    "ROC Filing",
    "Bookkeeping",
    "Company Incorporation",
    "TDS Return",
    "Financial Advisory",
    "Assurance",
    "Payroll",
    "Transfer Pricing",
    "FEMA",
    "Business Valuation",
]

DIRECTORY_SITES = ["justdial-clone", "sulekha-clone", "indiamart-clone", "grotal-clone"]

# A small maintained disposable-domain list (mock-side; real pipeline uses the
# disposable-email-domains package). Kept here so the corpora are self-contained.
DISPOSABLE_DOMAINS = [
    "mailinator.com",
    "10minutemail.com",
    "guerrillamail.com",
    "tempmail.com",
    "trashmail.com",
    "yopmail.com",
    "throwawaymail.com",
    "getnada.com",
    "sharklasers.com",
    "dispostable.com",
]


def _haversine_offset(rng: random.Random, center: tuple[float, float], max_km: float):
    """A uniformly-distributed random point within `max_km` of center."""
    # sqrt keeps the distribution uniform over the disk (not clustered at centre).
    dist = max_km * math.sqrt(rng.random())
    bearing = rng.uniform(0, 2 * math.pi)
    lat0, lng0 = center
    dlat = (dist / 111.0) * math.cos(bearing)
    dlng = (dist / (111.0 * math.cos(math.radians(lat0)))) * math.sin(bearing)
    return round(lat0 + dlat, 6), round(lng0 + dlng, 6)


def _domain_for(name: str, rng: random.Random) -> str:
    base = "".join(ch.lower() for ch in name if ch.isalnum())
    base = base[:22] or "cafirm"
    tld = rng.choice([".com", ".in", ".co.in", ".com"])
    return f"{base}{tld}"


def _phone(rng: random.Random) -> str:
    # Ahmedabad landline (STD 079) or mobile.
    if rng.random() < 0.5:
        return f"+91 79 {rng.randint(2000, 4999)} {rng.randint(1000, 9999)}"
    return f"+91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}"


def _firm_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(50):
        n_surnames = rng.choice([1, 1, 1, 2])
        parts = rng.sample(SURNAMES, n_surnames)
        prefix = rng.choice(FIRM_PREFIXES)
        suffix = rng.choice(FIRM_SUFFIXES)
        if n_surnames == 2:
            name = f"{prefix}{parts[0]} {parts[1]} {suffix}".strip()
        else:
            name = f"{prefix}{parts[0]} {suffix}".strip()
        if name not in used:
            used.add(name)
            return name
    # extreme fallback: append an index-like token
    name = f"{rng.choice(SURNAMES)} {rng.choice(SURNAMES)} & Associates ({rng.randint(1, 999)})"
    used.add(name)
    return name


def generate_companies(rng: random.Random, count: int) -> list[dict]:
    used_names: set[str] = set()
    companies = []
    for i in range(count):
        name = _firm_name(rng, used_names)
        locality, pincode = rng.choice(LOCALITIES)
        lat, lng = _haversine_offset(rng, AHMEDABAD_CENTER, RADIUS_KM)
        domain = _domain_for(name, rng)
        n_services = rng.randint(2, 5)
        services = rng.sample(SERVICES_POOL, n_services)
        # size band roughly matching the 50-200 demo filter, with spread
        size_lo = rng.choice([10, 25, 50, 50, 100, 150])
        size_hi = size_lo + rng.choice([15, 40, 50, 100])
        street_no = rng.randint(1, 999)
        floor = rng.choice(
            [
                "",
                f"{rng.randint(1, 8)}th Floor, ",
                "Ground Floor, ",
                f"{rng.randint(1, 8)}nd Floor, ",
            ]
        )
        bldg = rng.choice(
            [
                "Corporate House",
                "Business Hub",
                "Sapphire",
                "Iscon Elegance",
                "Time Square",
                "Pinnacle",
                "Shivalik Plaza",
                "Titanium City Centre",
                "Venus Atlantis",
                "Abhishek Complex",
                "Sun Avenue",
            ]
        )
        companies.append(
            {
                "idx": i,
                "name": name,
                "domain": domain,
                "website": f"https://www.{domain}",
                "phone": _phone(rng),
                "address": f"{floor}{bldg}, {street_no} {locality}, Ahmedabad, Gujarat {pincode}",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "country": "India",
                "postal_code": pincode,
                "locality": locality,
                "latitude": lat,
                "longitude": lng,
                "industry": "Chartered Accountants",
                "services": services,
                "company_size": f"{size_lo}-{size_hi}",
                "google_place_id": f"MOCKPLACE_{rng.getrandbits(64):016x}",
                "google_rating": round(rng.uniform(3.6, 4.9), 1),
                "google_reviews": rng.randint(8, 480),
            }
        )
    return companies


def generate_people(rng: random.Random) -> dict:
    """Name pools + designation weighting shared by website/enrichment mocks."""
    return {
        "surnames": SURNAMES,
        "first_names_m": FIRST_NAMES_M,
        "first_names_f": FIRST_NAMES_F,
        "designations": DESIGNATIONS,
        "role_inboxes": ROLE_INBOXES,
        "services_pool": SERVICES_POOL,
    }


def generate_directory_only(rng: random.Random, count: int, base_names: set[str]) -> list[dict]:
    """Unique companies that appear ONLY in directories (not Google Maps)."""
    used = set(base_names)
    out = []
    for i in range(count):
        name = _firm_name(rng, used)
        locality, pincode = rng.choice(LOCALITIES)
        lat, lng = _haversine_offset(rng, AHMEDABAD_CENTER, RADIUS_KM)
        domain = _domain_for(name, rng)
        out.append(
            {
                "idx": i,
                "name": name,
                "domain": domain,
                "website": f"https://www.{domain}",
                "phone": _phone(rng),
                "city": "Ahmedabad",
                "state": "Gujarat",
                "country": "India",
                "postal_code": pincode,
                "locality": locality,
                "latitude": lat,
                "longitude": lng,
                "industry": "Chartered Accountants",
                "services": rng.sample(SERVICES_POOL, rng.randint(1, 4)),
            }
        )
    return out


def generate_gated_sets(rng: random.Random) -> dict:
    """Small demo sets for AMBER/RED gated sources (yellow_pages/clutch/indeed/linkedin)."""

    def _mini(prefix: str, n: int) -> list[dict]:
        used: set[str] = set()
        rows = []
        for i in range(n):
            name = _firm_name(rng, used)
            domain = _domain_for(name, rng)
            locality, pincode = rng.choice(LOCALITIES)
            rows.append(
                {
                    "idx": i,
                    "name": name,
                    "domain": domain,
                    "website": f"https://www.{domain}",
                    "city": "Ahmedabad",
                    "state": "Gujarat",
                    "country": "India",
                    "postal_code": pincode,
                    "source_url": f"https://{prefix}.example/listing/{i}",
                    "industry": "Chartered Accountants",
                }
            )
        return rows

    return {
        "yellow_pages": _mini("yellowpages", 12),
        "clutch": _mini("clutch", 8),
        "indeed": _mini("indeed", 10),
        "linkedin": _mini("linkedin", 6),
    }


def build_corpora() -> dict[str, object]:
    rng = random.Random(SEED)
    companies = generate_companies(rng, 250)
    base_names = {c["name"] for c in companies}
    directory_only = generate_directory_only(rng, 60, base_names)
    people = generate_people(rng)
    gated = generate_gated_sets(rng)
    return {
        "google_maps_companies.json": companies,
        "directory_only_companies.json": directory_only,
        "people_pool.json": people,
        "gated_sources.json": gated,
        "disposable_domains.json": DISPOSABLE_DOMAINS,
    }


def write_corpora(corpora: dict[str, object]) -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, payload in corpora.items():
        path = DATA_DIR / filename
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False))
        written.append(path)
    return written


def _check() -> int:
    fresh = build_corpora()
    ok = True
    for filename, payload in fresh.items():
        path = DATA_DIR / filename
        if not path.exists():
            print(f"MISSING {path}")
            ok = False
            continue
        on_disk = json.loads(path.read_text())
        if on_disk != payload:
            print(f"DRIFT {path}")
            ok = False
    if ok:
        print("corpora up to date")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate mock seed corpora.")
    parser.add_argument("--check", action="store_true", help="verify committed == fresh")
    args = parser.parse_args()
    if args.check:
        return _check()
    corpora = build_corpora()
    paths = write_corpora(corpora)
    for p in paths:
        print(f"wrote {p}")
    print(
        f"companies={len(corpora['google_maps_companies.json'])} "
        f"directory_only={len(corpora['directory_only_companies.json'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
