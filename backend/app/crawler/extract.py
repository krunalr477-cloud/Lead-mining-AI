"""Crawl orchestration: homepage -> scored frontier -> per-page parse -> merge
into one ``ExtractionResult`` (spec §8 crawl loop, §9 extraction + dedup).

``crawl_company`` is the entry point the CompanyWebsitesAdapter calls. It:
1. resolves the homepage from company.website/domain,
2. checks robots.txt (skip + audit disallowed paths),
3. fetches pages tier-1/tier-2 under the per-domain rate limit and caps,
4. parses each page (emails/phones/JSON-LD/team/social/hiring),
5. merges page partials into a deduplicated ExtractionResult with per-contact
   source_page + snippet + confidence, applying a domain-alignment confidence
   boost when a contact's email domain matches the site domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import (
    ExtractedContact,
    ExtractedHiringSignal,
    ExtractionResult,
)
from app.config import get_settings
from app.constants import HiringSignalType
from app.crawler.fetcher import CrawlBudget, PageFetcher
from app.crawler.frontier import Frontier, registrable_domain
from app.crawler.parsers import emails as email_parser
from app.crawler.parsers import phones as phone_parser
from app.crawler.parsers.jsonld import parse_jsonld
from app.crawler.parsers.names import derive_name_from_local, is_plausible_person_name
from app.crawler.parsers.social import detect_hiring_signals, extract_social_links
from app.crawler.parsers.team_pages import classify_designation, extract_team_members
from app.crawler.robots import fetch_robots
from app.pipeline.validation import is_role_based

if TYPE_CHECKING:
    from app.adapters.base import CompanyRef
    from app.adapters.context import SourceRunContext

__all__ = ["crawl_company", "parse_page", "PagePartial"]


@dataclass(slots=True)
class PagePartial:
    """Everything harvested from a single page."""

    url: str
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    social: dict[str, str] = field(default_factory=dict)
    contacts: list[ExtractedContact] = field(default_factory=list)
    hiring: list[ExtractedHiringSignal] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    about_text: str | None = None
    links: list[tuple[str, str]] = field(default_factory=list)
    footer_links: list[tuple[str, str]] = field(default_factory=list)


def _split_name(name: str) -> tuple[str | None, str | None]:
    parts = name.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def _homepage(company: CompanyRef) -> str | None:
    if company.website:
        url = company.website.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url
    if company.domain:
        host = company.domain.strip()
        if host.startswith("www."):
            host = host[4:]
        return f"https://{host}"
    return None


def _homepage_candidates(company: CompanyRef) -> list[str]:
    """Ordered homepage URL variants: the listed URL first, then the http/https
    scheme swap and the www toggle. A DNS/connect failure on the exact listed URL
    is often just a canonicalization quirk (https-only listing for an http-only
    site, bare host vs www) — one cheap probe per variant recovers those."""
    base = _homepage(company)
    if not base:
        return []
    parsed = urlsplit(base)
    scheme, host = parsed.scheme or "https", parsed.netloc
    path = parsed.path or ""
    alt_scheme = "http" if scheme == "https" else "https"
    candidates = [base, f"{alt_scheme}://{host}{path}"]
    hostname = host.rsplit(":", 1)[0]
    is_ip = hostname.replace(".", "").isdigit()
    if ":" not in host and not is_ip:  # www-toggle makes no sense for IPs/ports
        toggled = host[4:] if host.startswith("www.") else f"www.{host}"
        candidates.append(f"{scheme}://{toggled}{path}")
        candidates.append(f"{alt_scheme}://{toggled}{path}")
    seen: set[str] = set()
    out: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out[:4]


def parse_page(url: str, html: str, *, country: str | None = None) -> PagePartial:
    """Parse one page's HTML into a PagePartial (pure; no network)."""
    soup = BeautifulSoup(html, "lxml")
    partial = PagePartial(url=url)

    visible_text = soup.get_text(" ", strip=True)

    # -- emails: mailto + cfemail + obfuscated + regex ---------------------- #
    partial.emails = email_parser.extract_emails(text=visible_text, html=html, soup=soup)

    # -- phones: tel + regex, region from company country ------------------- #
    partial.phones = phone_parser.extract_phones(text=visible_text, soup=soup, country=country)

    # -- JSON-LD structured data ------------------------------------------- #
    ld_blocks = [
        s.string or s.get_text() for s in soup.find_all("script", type="application/ld+json")
    ]
    ld = parse_jsonld([b for b in ld_blocks if b])
    for e in ld.emails:
        if e not in partial.emails:
            partial.emails.append(e)
    for p in phone_parser.extract_phones(text=" ".join(ld.phones), country=country):
        if p not in partial.phones:
            partial.phones.append(p)

    # JSON-LD people -> contacts (gated: reject template/placeholder Person nodes
    # like "Template"/"boilerplate" that CMSes emit with @type Person).
    for person in ld.people:
        if not is_plausible_person_name(person.name):
            continue
        first, last = _split_name(person.name or "")
        designation = (
            person.job_title if (person.job_title and len(person.job_title) <= 80) else None
        )
        role = classify_designation(designation) if designation else None
        partial.contacts.append(
            ExtractedContact(
                full_name=person.name,
                first_name=first,
                last_name=last,
                designation=designation,
                seniority=role[0] if role else None,
                role_category=role[1] if role else None,
                email=person.email,
                phone=person.telephone,
                linkedin_url=next((s for s in person.same_as if "linkedin" in s.lower()), None),
                source_page=url,
                source_type="jsonld",
                source_snippet=f"{person.name} — {designation or ''}".strip(" —"),
                confidence_score=0.78,  # structured data, but capped below verified emails
            )
        )

    # JSON-LD job postings -> hiring signals
    for job in ld.jobs:
        partial.hiring.append(
            ExtractedHiringSignal(
                source="company_website",
                signal_type=HiringSignalType.JOB_POSTING,
                source_url=job.url or url,
                job_title=job.title,
                location=job.location,
                posted_at=job.date_posted,
                description_excerpt=(job.description or "")[:280] or None,
                confidence_score=0.8,
            )
        )

    # -- team / leadership cards ------------------------------------------- #
    for member in extract_team_members(soup):
        first, last = _split_name(member.name)
        partial.contacts.append(
            ExtractedContact(
                full_name=member.name,
                first_name=first,
                last_name=last,
                designation=member.designation,
                seniority=member.seniority,
                role_category=member.role_category,
                email=None,
                source_page=url,
                source_type="team_page",
                source_snippet=member.snippet,
                confidence_score=member.confidence,
            )
        )

    # -- social links (anchors + JSON-LD sameAs) --------------------------- #
    partial.social = extract_social_links(soup=soup, extra_urls=ld.same_as)

    # -- hiring keyword phrases -------------------------------------------- #
    for _phrase, snippet in detect_hiring_signals(visible_text):
        partial.hiring.append(
            ExtractedHiringSignal(
                source="company_website",
                signal_type=HiringSignalType.PUBLIC_POST,
                source_url=url,
                description_excerpt=snippet[:280],
                confidence_score=0.55,
                job_title=None,
            )
        )

    # -- about text (from JSON-LD desc, else meta description) ------------- #
    if ld.description:
        partial.about_text = ld.description[:600]
    else:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            partial.about_text = meta["content"].strip()[:600]

    # -- link harvesting for the frontier ---------------------------------- #
    footer = soup.find("footer")
    footer_anchors = set()
    if footer:
        for a in footer.find_all("a", href=True):
            partial.footer_links.append((a["href"], a.get_text(" ", strip=True)))
            footer_anchors.add(a["href"])
    for a in soup.find_all("a", href=True):
        if a["href"] not in footer_anchors:
            partial.links.append((a["href"], a.get_text(" ", strip=True)))

    return partial


def _mint_role_contacts(emails: list[str], domain: str, url: str) -> list[ExtractedContact]:
    """Turn bare emails with no owning person into contacts.

    Role inboxes (info@, careers@) are labeled ``role_inbox`` via the real
    tokenized ``is_role_based`` check — not a digit heuristic that wrongly tagged
    ``derek.johnson@`` as a role inbox. Person-shaped locals get a derived name
    ("derek.johnson" -> "Derek Johnson") and rank ABOVE role inboxes.
    """
    out: list[ExtractedContact] = []
    for email in emails:
        local = email.split("@", 1)[0]
        if is_role_based(email):
            out.append(
                ExtractedContact(
                    email=email,
                    full_name=None,
                    source_page=url,
                    source_type="crawler_email",
                    source_snippet=email,
                    confidence_score=0.4,
                    role_category="role_inbox",
                )
            )
            continue
        derived = derive_name_from_local(local)
        full = first = last = None
        if derived:
            full, first, last = derived
        out.append(
            ExtractedContact(
                email=email,
                full_name=full,
                first_name=first,
                last_name=last,
                source_page=url,
                source_type="crawler_email",
                source_snippet=email,
                confidence_score=0.68 if full else 0.55,
                role_category=None,
            )
        )
    return out


async def crawl_company(company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
    """Crawl one company's website and return a merged ExtractionResult.

    The homepage is resolved across scheme/www variants with a retry ladder, so
    a transient DNS blip or a canonicalization quirk doesn't permanently mark a
    live site unreachable. A homepage exhausted on 403/503 (WAF block, even via
    Playwright) is recorded as ``blocked`` — distinct from truly ``unreachable``.
    """
    candidates = _homepage_candidates(company)
    if not candidates:
        return ExtractionResult(website_status="no_website", pages_crawled=[])

    settings = get_settings()
    max_pages = settings.crawler_max_pages_per_domain
    budget = CrawlBudget(max_pages=max_pages)

    partials: list[PagePartial] = []
    pages_crawled: list[str] = []
    website_status = "ok"
    any_fetched = False
    site_domain = company.domain.lower() if company.domain else ""

    def _may_use_playwright() -> bool:
        """Per-job Playwright budget (Redis counter; fail-open without Redis)."""
        try:
            key = f"job:{ctx.job_id}:pw_attempts"
            n = int(ctx.redis.incr(key))
            if n == 1:
                ctx.redis.expire(key, 86_400)
            return n <= settings.crawler_playwright_max_per_job
        except Exception:
            return True

    timeout = httpx.Timeout(15.0, connect=10.0)
    fetcher: PageFetcher | None = None
    try:
        async with httpx.AsyncClient(
            http2=True, timeout=timeout, max_redirects=5, verify=True
        ) as client:
            # --- resolve a reachable homepage across URL variants ------------ #
            homepage: str | None = None
            policy = None
            seed_result = None
            last_error_kind: str | None = None
            for idx, candidate in enumerate(candidates):
                parsed = urlsplit(candidate)
                pol = await fetch_robots(client, parsed.scheme or "https", parsed.netloc, ctx)
                if not pol.allowed(candidate):
                    # robots forbids the homepage — honor it; variants of the
                    # same site would carry the same rules.
                    ctx.audit(candidate, status="skipped_robots", records_found=0)
                    last_error_kind = "robots"
                    break
                # Honor robots Crawl-delay (already capped at 10s) when stricter
                # than our configured per-domain politeness delay (spec §8).
                per_domain_delay = settings.crawler_per_domain_delay_seconds
                if pol.crawl_delay is not None:
                    per_domain_delay = max(per_domain_delay, pol.crawl_delay)
                fetcher = PageFetcher(
                    client,
                    per_domain_delay=per_domain_delay,
                    may_use_playwright=_may_use_playwright,
                )
                # Full retry ladder on the listed URL; single cheap probe per variant.
                result = await fetcher.fetch(candidate, attempts=None if idx == 0 else 1)
                budget.record()
                if result.ok:
                    homepage, policy, seed_result = candidate, pol, result
                    if result.ssl_insecure:
                        ctx.audit(candidate, status="ok_ssl_invalid", records_found=0)
                    break
                detail = f"{result.error_kind}: {result.error}" if result.error_kind else result.error
                ctx.audit(candidate, status="error", error=(detail or "")[:200])
                last_error_kind = result.error_kind
                if result.error_kind not in ("dns", "connect"):
                    break  # only DNS/connect failures justify probing URL variants

            if seed_result is None or homepage is None or policy is None:
                status = "blocked" if last_error_kind in ("http_403", "http_503") else "unreachable"
                return ExtractionResult(website_status=status, pages_crawled=[])

            # --- crawl the site from the resolved homepage -------------------- #
            domain = registrable_domain(homepage)
            site_domain = company.domain.lower() if company.domain else domain
            frontier = Frontier(seed_url=homepage, domain=domain)
            frontier.mark_visited(homepage)
            any_fetched = True
            ctx.audit(f"tier{seed_result.tier}:{homepage}", status="ok", records_found=0)
            partial = parse_page(homepage, seed_result.html, country=company.country)
            partials.append(partial)
            pages_crawled.append(homepage)
            frontier.add_links(homepage, partial.links)
            frontier.add_links(homepage, partial.footer_links, in_footer=True)

            queue = [
                link.url
                for link in frontier.top(max(0, max_pages - budget.pages_fetched))
                if link.score > 0
            ]
            while queue and budget.can_fetch():
                url = queue.pop(0)
                if frontier.visited(url):
                    continue

                if not policy.allowed(url):
                    ctx.audit(url, status="skipped_robots", records_found=0)
                    frontier.mark_visited(url)
                    continue

                # Sub-pages: single attempt — the site is proven up, and a lost
                # page shouldn't burn the retry ladder.
                result = await fetcher.fetch(url, attempts=1)
                budget.record()
                frontier.mark_visited(url)

                if not result.ok:
                    ctx.audit(url, status="error", error=result.error)
                    continue

                ctx.audit(
                    f"tier{result.tier}:{url}",
                    status="ok",
                    records_found=0,
                )
                partial = parse_page(url, result.html, country=company.country)
                partials.append(partial)
                pages_crawled.append(url)

                # Feed the frontier, then top up the queue from best links.
                frontier.add_links(url, partial.links)
                frontier.add_links(url, partial.footer_links, in_footer=True)
                remaining = max_pages - budget.pages_fetched
                if remaining > 0:
                    for link in frontier.top(remaining):
                        if link.score > 0 and link.url not in queue:
                            queue.append(link.url)
    except Exception as exc:  # defensive: a crawl error must not kill the job
        ctx.audit(candidates[0], status="error", error=str(exc)[:200])
        if not any_fetched:
            return ExtractionResult(website_status="unreachable", pages_crawled=pages_crawled)
    finally:
        if fetcher is not None:
            await fetcher.aclose()

    if not any_fetched:
        website_status = "unreachable"

    return _merge(partials, site_domain, pages_crawled, website_status)


def _merge(
    partials: list[PagePartial],
    site_domain: str,
    pages_crawled: list[str],
    website_status: str,
) -> ExtractionResult:
    """Merge page partials into one deduplicated ExtractionResult."""
    emails: list[str] = []
    phones: list[str] = []
    social: dict[str, str] = {}
    hiring: list[ExtractedHiringSignal] = []
    about_text: str | None = None

    for partial in partials:
        for e in partial.emails:
            if e not in emails:
                emails.append(e)
        for p in partial.phones:
            if p not in phones:
                phones.append(p)
        for key, val in partial.social.items():
            social.setdefault(key, val)
        hiring.extend(partial.hiring)
        if about_text is None and partial.about_text:
            about_text = partial.about_text

    # -- contact dedup + email attach + domain-alignment boost ------------- #
    contacts: dict[str, ExtractedContact] = {}
    for partial in partials:
        for contact in partial.contacts:
            key = (contact.full_name or contact.email or "").strip().lower()
            if not key:
                continue
            existing = contacts.get(key)
            if existing is None:
                contacts[key] = contact
            else:
                # Merge: keep highest confidence, fill missing email/designation.
                if contact.email and not existing.email:
                    existing.email = contact.email
                if contact.designation and not existing.designation:
                    existing.designation = contact.designation
                    existing.seniority = existing.seniority or contact.seniority
                    existing.role_category = existing.role_category or contact.role_category
                if contact.confidence_score > existing.confidence_score:
                    existing.confidence_score = contact.confidence_score
                    existing.source_page = contact.source_page
                    existing.source_snippet = contact.source_snippet

    # Attach unowned emails as role/email contacts and apply domain boost.
    owned = {c.email for c in contacts.values() if c.email}
    unowned = [e for e in emails if e not in owned]
    example_url = pages_crawled[0] if pages_crawled else ""
    for extra in _mint_role_contacts(unowned, site_domain, example_url):
        key = extra.email or ""
        contacts.setdefault(key.lower(), extra)

    final_contacts = list(contacts.values())
    for contact in final_contacts:
        if contact.email and site_domain and contact.email.split("@")[-1].lower() == site_domain:
            contact.confidence_score = round(min(contact.confidence_score + 0.1, 0.99), 3)

    # De-dup hiring signals by (type, title, excerpt).
    seen_sig: set[tuple] = set()
    deduped_hiring: list[ExtractedHiringSignal] = []
    for sig in hiring:
        sig_key = (sig.signal_type, sig.job_title, (sig.description_excerpt or "")[:40])
        if sig_key in seen_sig:
            continue
        seen_sig.add(sig_key)
        deduped_hiring.append(sig)

    return ExtractionResult(
        contacts=final_contacts,
        emails=emails,
        phones=phones,
        social_links=social,
        services=[],
        about_text=about_text,
        hiring_signals=deduped_hiring,
        pages_crawled=pages_crawled,
        website_status=website_status,
    )
