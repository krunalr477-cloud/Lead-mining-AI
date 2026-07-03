"""MockCompanyWebsitesAdapter (GREEN) — deterministic per-company deep dive.

``discover`` yields nothing (this source only deep-dives companies already found
by Maps/directories). ``extract`` synthesizes a stable set of contacts, emails,
phones, social links, and (some of the time) a hiring signal for one company,
seeded from the company's STABLE identity (its domain/name) — not the row's
uuid7 primary key, which is minted fresh on every insert — so a company's people
reproduce exactly across seed/verify re-runs regardless of insert order.

Emails are minted in a mix of person@domain and role@domain patterns so the
validation pipeline exercises every stage (syntax pass, disposable reject,
role-based reject, MX pass, verifier buckets). A small fraction of contacts are
left email-less so the enrichment stage has real work to do.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import TYPE_CHECKING

from app.adapters.base import (
    CompanyRef,
    DiscoveredCompany,
    ExtractedContact,
    ExtractedHiringSignal,
    ExtractionResult,
    JobSpec,
    SourceAdapter,
)
from app.adapters.mock._common import load_corpus, rng_from, stable_unit
from app.constants import AccessMethod, HiringSignalType, Posture, SourceName
from app.db import utcnow

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["MockCompanyWebsitesAdapter"]

_DISPOSABLE = ["mailinator.com", "guerrillamail.com", "tempmail.com", "yopmail.com"]


def _person_email(first: str, last: str, domain: str, rng) -> str:
    local = rng.choice(
        [
            f"{first}.{last}",
            f"{first}{last}",
            f"{first[0]}{last}",
            f"{first}",
            f"{first}_{last}",
        ]
    ).lower()
    return f"{local}@{domain}"


class MockCompanyWebsitesAdapter(SourceAdapter):
    name = SourceName.COMPANY_WEBSITES
    source_type = "crawler"
    access_method = AccessMethod.MOCK
    posture = Posture.GREEN
    default_enabled = True
    requires_signoff = False
    required_credentials = []
    legal_note = "Polite crawl of public company pages. Demo data in mock mode."

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        # This source never independently discovers companies; it only enriches
        # ones already found. Yield nothing.
        return
        yield  # pragma: no cover - makes this an async generator

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        people: dict = load_corpus("people_pool.json")  # type: ignore[assignment]
        domain = company.domain or "example.com"
        website = company.website or f"https://www.{domain}"
        # Seed from a STABLE company identity (domain/name), not the row's uuid7
        # primary key, so a company's people reproduce across seed runs regardless
        # of insert order (the DB id is minted fresh on every re-seed).
        seed_key = company.domain or company.name or str(company.company_id)
        rng = rng_from(seed_key, "website")

        ctx.audit(f"crawl:{website}", status="ok", records_found=0)

        n_contacts = rng.randint(1, 4)
        designations = people["designations"]
        surnames = people["surnames"]
        first_m = people["first_names_m"]
        first_f = people["first_names_f"]

        contacts: list[ExtractedContact] = []
        emails: list[str] = []
        pages = [website, f"{website}/about", f"{website}/team", f"{website}/contact"]

        for i in range(n_contacts):
            # ~30% female-name pool, otherwise male pool (demo corpus split).
            if stable_unit(seed_key, "sex", i) < 0.30:
                first = rng.choice(first_f)
            else:
                first = rng.choice(first_m)
            last = rng.choice(surnames)
            title, seniority, dept, role_cat = rng.choice(designations)

            bucket = stable_unit(seed_key, "email", i)
            email: str | None
            if bucket < 0.41:
                # Leave email-less -> drives enrichment (spec §21: ~73% of
                # contacts end up with an email once enrichment recovers a share).
                email = None
            elif bucket < 0.425:
                # Role inbox (info@, contact@ ...) -> role-based rejection stage.
                email = f"{rng.choice(people['role_inboxes'])}@{domain}"
            elif bucket < 0.44:
                # Disposable domain -> disposable rejection stage.
                email = f"{first.lower()}.{last.lower()}@{rng.choice(_DISPOSABLE)}"
            else:
                email = _person_email(first, last, domain, rng)

            if email:
                emails.append(email)

            contacts.append(
                ExtractedContact(
                    full_name=f"{first} {last}",
                    first_name=first,
                    last_name=last,
                    designation=title,
                    department=dept,
                    seniority=seniority,
                    role_category=role_cat,
                    email=email,
                    phone=None,
                    linkedin_url=f"https://www.linkedin.com/in/{first.lower()}-{last.lower()}",
                    source_page=rng.choice(pages),
                    source_type="crawler",
                    source_snippet=f"{first} {last}, {title} at {company.name}",
                    confidence_score=round(0.6 + 0.35 * stable_unit(seed_key, "conf", i), 3),
                    is_demo=True,
                )
            )

        # ~35% of companies expose a public hiring signal (careers page / posting).
        hiring: list[ExtractedHiringSignal] = []
        if stable_unit(seed_key, "hiring") < 0.35:
            svc = rng.choice(people["services_pool"])
            hiring.append(
                ExtractedHiringSignal(
                    source="company_website",
                    signal_type=HiringSignalType.CAREERS_PAGE,
                    source_url=f"{website}/careers",
                    job_title=f"{svc} Associate",
                    location=company.city or "Ahmedabad",
                    posted_at=utcnow() - timedelta(days=rng.randint(1, 40)),
                    description_excerpt=f"Hiring {svc} associate — public careers page.",
                    confidence_score=round(0.5 + 0.4 * stable_unit(seed_key, "hconf"), 3),
                )
            )

        return ExtractionResult(
            contacts=contacts,
            emails=emails,
            phones=[],
            social_links={"linkedin": f"https://www.linkedin.com/company/{domain.split('.')[0]}"},
            services=list(company.name and people["services_pool"][:3] or []),
            about_text=f"{company.name} is a chartered-accountancy firm in {company.city or 'Ahmedabad'}.",
            hiring_signals=hiring,
            pages_crawled=pages,
            website_status="ok",
        )
