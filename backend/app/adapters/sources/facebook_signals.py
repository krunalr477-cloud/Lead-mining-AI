"""FacebookSignalsAdapter (AMBER) — REAL compliance-gated Facebook signals.

Spec §8 "Source: Facebook Pages and Hiring Signals":
- Compliance-gated connector, NOT uncontrolled scraping.
- Use official Meta/Graph API access ONLY where the tenant has permission and the
  API allows the data.
- NEVER scrape private profiles, private groups, Messenger, or authenticated-only
  user data. NEVER ask for personal Facebook credentials. NEVER automate login.
- NEVER collect personal user profile data from Facebook.
- If no compliant Facebook access exists, fail GRACEFULLY with a clear message;
  the rest of the mining job continues.

Three supported modes (spec §8):

1. Authorized Business/Page mode
   - For Pages the tenant controls or is authorized to access.
   - Reads a *Page access token* from ``IntegrationCredential(provider="facebook")``
     (Fernet-encrypted at rest) and calls the official Graph API to read
     permitted PUBLIC page fields only: ``id, name, link, category, website,
     phone, emails, single_line_address``. No posts/insights/followers unless the
     token's own permissions allow it — we request only the low-sensitivity
     public business fields above.
   - Endpoint: ``GET https://graph.facebook.com/v19.0/{page-id}``. This is a
     PAGE-NODE read, never a ``/me`` user read, never a profile/group/messenger
     endpoint.

2. Public page signal mode
   - Uses the approved SERP provider (the same ``serp_api_key`` / ``serp_provider``
     the jobs source uses) to discover PUBLIC ``facebook.com`` Page URLs via a
     ``site:facebook.com "<company>" <city>`` web search.
   - Captures ONLY the public page URL, page name and category from the search
     result — NO profile data, NO login, NO page-content scraping.
   - Endpoint: the SERP provider's public web-search API (serpapi.com). We never
     fetch ``facebook.com`` HTML ourselves.

3. Hiring signal fallback
   - When Facebook jobs data is not available through official access, detect
     hiring via the company careers page and Google Jobs / SERP Jobs, stored as
     ``ExtractedHiringSignal`` (HiringSignal records) — NOT as verified contacts.

Access resolution / graceful failure
-------------------------------------
- ``discover`` (mode 2) needs the SERP key; without it, it audits a clear
  "no compliant public-page access" skip and yields nothing.
- ``extract`` tries mode 1 (page token) first, then falls back to mode 3
  (careers/SERP jobs). With neither a page token nor a SERP key it records a
  clear "no compliant Facebook access" audit and returns an empty result.
- ``check_access`` returns a ``SourceUnavailable`` (with a human reason) when no
  compliant mode can run, so callers can surface the exact refusal message.

Real-vs-mock activation is decided by the registry: the real factory builds this
adapter only when SOME compliant access could exist (a SERP key OR a stored
Facebook page credential); otherwise the registry serves the mock. Whatever is
built, this adapter touches ONLY public web-search and Graph *page-node*
endpoints — never a login, profile, group, or Messenger endpoint.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sqlalchemy import select

from app.adapters._http import ProviderError, ProviderRateLimited, audited_request
from app.adapters.base import (
    CompanyRef,
    DiscoveredCompany,
    ExtractedHiringSignal,
    ExtractionResult,
    JobSpec,
    SourceAdapter,
    SourceUnavailable,
)
from app.config import get_settings
from app.constants import AccessMethod, HiringSignalType, Posture, SourceName
from app.models import IntegrationCredential
from app.security.crypto import get_cipher

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = [
    "FacebookSignalsAdapter",
    "GRAPH_API_BASE",
    "SERPAPI_SEARCH_URL",
    "FACEBOOK_PROVIDER",
    "facebook_page_from_url",
]

# Graph API version pinned; we only ever read a PAGE node (never /me, never a
# user/profile/group/messenger node). See PAGE_FIELDS below.
GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

# Approved SERP provider public web-search endpoint (serpapi). Mode 2 and mode 3
# both go through this — we never fetch facebook.com HTML directly.
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"

FACEBOOK_PROVIDER = "facebook"

# The ONLY Graph fields we request: low-sensitivity PUBLIC business-page fields.
# Deliberately NO followers/insights/posts/fan data and NOTHING about people.
PAGE_FIELDS = "id,name,link,category,website,phone,emails,single_line_address"

# Unit costs (approx) for cost accounting.
_SERP_UNIT_COST = 0.005
_GRAPH_UNIT_COST = 0.0  # first-party Graph reads are quota-based, not per-call priced.

# Hiring intent keywords for public-post / SERP snippets (mode 3 signal).
_HIRING_TERMS = re.compile(
    r"\b(hiring|we\s*'?re\s+hiring|now\s+hiring|join\s+our\s+team|careers?|"
    r"vacanc(?:y|ies)|open\s+positions?|job\s+openings?|apply\s+now|recruit)\b",
    re.IGNORECASE,
)

# Host allowlist for what we treat as a public Facebook *Page* URL. We keep only
# the page slug/id path — never a profile.php, groups, messenger, or watch URL.
_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.com"}
_NON_PAGE_PATH_PREFIXES = (
    "/profile.php",  # personal profile
    "/people/",  # personal profile
    "/groups/",  # group
    "/messages/",  # messenger
    "/watch",  # video feed
    "/marketplace",  # marketplace
    "/events/",  # event
    "/story.php",  # personal story
    "/photo",  # photo permalink
    "/permalink.php",  # post permalink
)


def facebook_page_from_url(url: str | None) -> str | None:
    """Return a normalized public Facebook *Page* URL, or None.

    Accepts only ``facebook.com/<page-slug>`` style links; rejects personal
    profiles, groups, Messenger, events, and post/photo permalinks so we never
    capture personal-profile data (spec §8). Query strings/fragments are dropped.
    """
    if not url:
        return None
    candidate = url if "//" in url else f"//{url}"
    parts = urlsplit(candidate)
    host = (parts.hostname or "").lower()
    if host not in _FACEBOOK_HOSTS:
        return None
    path = parts.path or "/"
    low = path.lower()
    for banned in _NON_PAGE_PATH_PREFIXES:
        if low.startswith(banned):
            return None
    # A page URL must have a non-empty first path segment (the page slug/id).
    slug = path.strip("/").split("/")[0]
    if not slug:
        return None
    return f"https://www.facebook.com/{slug}"


def _serp_web_query(company: str, city: str | None) -> str:
    """``site:facebook.com "<company>" <city>`` — public web search only."""
    q = f'site:facebook.com "{company}"'
    if city:
        q += f" {city}"
    return q


class FacebookSignalsAdapter(SourceAdapter):
    """REAL compliance-gated Facebook signals source (AMBER).

    Posture/gating are enforced by the registry (enable + sign-off +
    ``enable_facebook_signals``). This class enforces the *access* contract: it
    only ever calls public web-search and Graph page-node endpoints and refuses
    (gracefully) when no compliant mode can run.
    """

    name = SourceName.FACEBOOK_SIGNALS
    source_type = "graph_api"
    access_method = AccessMethod.LICENSED_PROVIDER
    posture = Posture.AMBER
    default_enabled = False
    requires_signoff = True
    required_credentials: list[str] = []  # access is optional-any: page token OR SERP key
    legal_note = (
        "Compliance-gated. Official Meta/Graph API for tenant-authorized Pages, "
        "plus approved SERP discovery of PUBLIC facebook.com Page URLs and "
        "careers/SERP hiring signals. NO login, NO private profiles/groups/"
        "Messenger, NO personal user data. Fails gracefully if no compliant "
        "access exists."
    )

    # -- access resolution --------------------------------------------------- #

    def _serp_key(self) -> str | None:
        key = get_settings().serp_api_key
        return key or None

    def _page_credential(self, ctx: SourceRunContext) -> IntegrationCredential | None:
        """Active per-tenant Facebook Page credential, if any (mode 1).

        Resolved from ``ctx`` (session + tenant) at run time — the registry builds
        one stateless adapter and the per-tenant credential is only known once a
        job's context exists. DB-free contexts (tests) simply yield no credential.
        """
        session = getattr(ctx, "session", None)
        tenant_id = getattr(ctx, "tenant_id", None)
        if session is None or tenant_id is None:
            return None
        return session.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant_id,
                IntegrationCredential.provider == FACEBOOK_PROVIDER,
                IntegrationCredential.status == "active",
            )
        )

    def check_access(self, ctx: SourceRunContext) -> SourceUnavailable | None:
        """None if some compliant mode can run; else a SourceUnavailable reason.

        This is the graceful-refusal path (spec §8): callers can surface the
        exact message. It NEVER raises and NEVER touches the network.
        """
        if self._serp_key() is not None or self._page_credential(ctx) is not None:
            return None
        return SourceUnavailable(
            self.name.value,
            "no compliant Facebook access: no authorized Page credential and no "
            "approved SERP provider key configured",
            self.posture,
        )

    # -- mode 1: authorized Page (Graph API page-node read) ------------------ #

    async def _read_authorized_page(
        self, cred: IntegrationCredential, ref: CompanyRef, ctx: SourceRunContext
    ) -> dict[str, Any] | None:
        """Read permitted PUBLIC page fields for a tenant-authorized Page.

        The credential stores a Fernet-encrypted ``<page_id>:<page_token>`` (or a
        page token alone with the page id in ``scopes[0]``). We call the Graph
        *page node* only, requesting the low-sensitivity PAGE_FIELDS. Returns the
        raw field dict or None (no page id / transient error).
        """
        page_id, token = self._decrypt_page_secret(cred)
        if not page_id or not token:
            return None
        url = f"{GRAPH_API_BASE}/{page_id}"
        # Audit trail is key-free: the token never enters the audit URL.
        audit_url = f"graph:{page_id}?fields={PAGE_FIELDS}"
        try:
            response = await audited_request(
                ctx,
                "GET",
                url,
                audit_url=audit_url,
                params={"fields": PAGE_FIELDS, "access_token": token},
            )
        except ProviderRateLimited:
            return None  # transient — don't fail the job
        except ProviderError:
            return None  # e.g. token lacks permission / page not found
        ctx.record_usage(FACEBOOK_PROVIDER, "graph.page", unit_cost=_GRAPH_UNIT_COST)
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _decrypt_page_secret(cred: IntegrationCredential) -> tuple[str | None, str | None]:
        """Decrypt the stored page secret into ``(page_id, page_token)``.

        Storage format: Fernet-encrypted ``"<page_id>:<token>"``. If the plaintext
        has no colon it is treated as the token and the page id is read from
        ``scopes[0]`` (page-id list).
        """
        try:
            plaintext = get_cipher().decrypt(cred.encrypted_secret_reference)
        except Exception:  # noqa: BLE001 — corrupt/rotated key: treat as no access
            return (None, None)
        if ":" in plaintext:
            page_id, token = plaintext.split(":", 1)
            return (page_id.strip() or None, token.strip() or None)
        page_id = (cred.scopes[0] if cred.scopes else "") or None
        return (page_id, plaintext.strip() or None)

    def _signal_from_page_fields(
        self, fields: dict[str, Any], ref: CompanyRef
    ) -> ExtractedHiringSignal | None:
        """A public page-post/about string mentioning hiring -> a signal.

        Mode 1 only surfaces a HIRING signal when a permitted public field clearly
        mentions hiring (spec §8 mode 3 semantics applied to authorized data). We
        never store personal data — only the public page link + snippet.
        """
        haystacks = [
            str(fields.get("about") or ""),
            str(fields.get("single_line_address") or ""),
            str(fields.get("name") or ""),
        ]
        blob = " ".join(h for h in haystacks if h)
        if not _HIRING_TERMS.search(blob):
            return None
        link = facebook_page_from_url(fields.get("link"))
        return ExtractedHiringSignal(
            source="facebook_page",
            signal_type=HiringSignalType.PUBLIC_POST,
            source_url=link,
            job_title=None,
            location=fields.get("single_line_address") or ref.city,
            posted_at=None,
            description_excerpt=("Authorized Facebook Page public field indicates active hiring."),
            confidence_score=0.6,
        )

    # -- mode 2: public page discovery via SERP ------------------------------ #

    async def _serp_web_search(
        self, query: str, ctx: SourceRunContext, *, endpoint: str
    ) -> dict[str, Any] | None:
        """One approved-provider public web search. Returns parsed JSON or None."""
        key = self._serp_key()
        if key is None:
            return None
        params = {
            "engine": "google",
            "q": query,
            "api_key": key,
            "num": "10",
        }
        audit_url = f"serpapi:search?engine=google&q={query}"
        try:
            response = await audited_request(
                ctx, "GET", SERPAPI_SEARCH_URL, audit_url=audit_url, params=params
            )
        except (ProviderRateLimited, ProviderError):
            return None
        ctx.record_usage("serpapi", endpoint, unit_cost=_SERP_UNIT_COST)
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _first_facebook_page(payload: dict[str, Any]) -> dict[str, str] | None:
        """Extract the first PUBLIC facebook Page {url,name,category} from SERP.

        Reads ONLY search-result metadata (link/title/rich_snippet). Never any
        profile data. Non-page facebook links (profiles/groups/etc.) are dropped
        by ``facebook_page_from_url``.
        """
        for result in payload.get("organic_results") or []:
            page_url = facebook_page_from_url(result.get("link"))
            if page_url is None:
                continue
            title = str(result.get("title") or "").strip()
            # SERP titles look like "Acme Ltd | Facebook" / "Acme Ltd - Home | Facebook".
            name = re.split(r"\s*[|\-–]\s*", title)[0].strip() or None
            category = None
            rich = result.get("rich_snippet") or {}
            top = rich.get("top") or {}
            exts = top.get("extensions") or []
            if exts:
                category = str(exts[0]).strip() or None
            return {
                "url": page_url,
                "name": name or "",
                "category": category or "",
            }
        return None

    async def discover(
        self, job: JobSpec, ctx: SourceRunContext
    ) -> AsyncIterator[DiscoveredCompany]:
        """Mode 2 — discover PUBLIC facebook.com Page URLs via the SERP provider.

        Yields a ``DiscoveredCompany`` carrying ONLY the public page URL, name and
        category (industry). Captures NO profile data and never fetches
        facebook.com itself. Without a SERP key it audits a clear skip and yields
        nothing (graceful failure — the job continues).
        """
        if self._serp_key() is None:
            ctx.audit(
                "facebook:public-page-discovery",
                status="skipped",
                error="no approved SERP provider key; public-page discovery unavailable",
            )
            return
        # We discover pages for the job's target company_type in the target city;
        # the search string is the same public web query pattern used per-company.
        company_term = job.company_type or (job.services[0] if job.services else None)
        if not company_term:
            ctx.audit(
                "facebook:public-page-discovery",
                status="skipped",
                error="no company term to search for",
            )
            return
        query = _serp_web_query(company_term, job.city)
        payload = await self._serp_web_search(query, ctx, endpoint="facebook.page.discovery")
        if not payload:
            return
        seen: set[str] = set()
        for result in payload.get("organic_results") or []:
            page_url = facebook_page_from_url(result.get("link"))
            if page_url is None or page_url in seen:
                continue
            seen.add(page_url)
            title = str(result.get("title") or "").strip()
            name = re.split(r"\s*[|\-–]\s*", title)[0].strip() or company_term
            category = None
            rich = result.get("rich_snippet") or {}
            exts = (rich.get("top") or {}).get("extensions") or []
            if exts:
                category = str(exts[0]).strip() or None
            yield DiscoveredCompany(
                name=name,
                source_name=self.name.value,
                source_url=page_url,
                facebook_page_url=page_url,
                industry=category,
                city=job.city,
                state=job.state,
                country=job.country,
                raw_payload={
                    "facebook_mode": "public_page_signal",
                    # ONLY public page metadata — explicitly no profile data.
                    "page_url": page_url,
                    "page_name": name,
                    "page_category": category,
                },
            )

    # -- mode 3: hiring-signal fallback (careers / SERP jobs) ---------------- #

    async def _serp_jobs_signals(
        self, ref: CompanyRef, ctx: SourceRunContext
    ) -> list[ExtractedHiringSignal]:
        """Google Jobs / SERP Jobs hiring signals for the company (mode 3)."""
        key = self._serp_key()
        if key is None:
            return []
        query = f"{ref.name} {ref.city}".strip()
        params = {
            "engine": "google_jobs",
            "q": query,
            "api_key": key,
        }
        audit_url = f"serpapi:google_jobs?q={query}"
        try:
            response = await audited_request(
                ctx, "GET", SERPAPI_SEARCH_URL, audit_url=audit_url, params=params
            )
        except (ProviderRateLimited, ProviderError):
            return []
        ctx.record_usage("serpapi", "facebook.hiring.jobs", unit_cost=_SERP_UNIT_COST)
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return []
        signals: list[ExtractedHiringSignal] = []
        for jobrow in payload.get("jobs_results") or []:
            title = str(jobrow.get("title") or "").strip() or None
            desc = str(jobrow.get("description") or "").strip()
            link = None
            for opt in jobrow.get("apply_options") or []:
                if opt.get("link"):
                    link = opt["link"]
                    break
            posted = _parse_posted_at((jobrow.get("detected_extensions") or {}).get("posted_at"))
            signals.append(
                ExtractedHiringSignal(
                    source="serp_jobs",
                    signal_type=HiringSignalType.JOB_POSTING,
                    source_url=link,
                    job_title=title,
                    location=str(jobrow.get("location") or ref.city or "") or None,
                    posted_at=posted,
                    description_excerpt=desc[:500] or None,
                    confidence_score=0.65,
                )
            )
        return signals

    async def _careers_signal(
        self, ref: CompanyRef, ctx: SourceRunContext
    ) -> ExtractedHiringSignal | None:
        """A company careers page counts as a hiring signal (mode 3 fallback).

        Uses the SERP provider to find a ``careers``/``jobs`` page on the
        company's own domain — we do NOT crawl it here (the website crawler owns
        deep crawling); its mere existence is the signal.
        """
        if self._serp_key() is None or not (ref.domain or ref.website):
            return None
        domain = (
            ref.domain
            or urlsplit(ref.website if "//" in (ref.website or "") else f"//{ref.website}").hostname
        )
        if not domain:
            return None
        query = f"site:{domain} (careers OR jobs OR hiring OR vacancies)"
        payload = await self._serp_web_search(query, ctx, endpoint="facebook.hiring.careers")
        if not payload:
            return None
        for result in payload.get("organic_results") or []:
            link = str(result.get("link") or "")
            title = str(result.get("title") or "")
            snippet = str(result.get("snippet") or "")
            if _HIRING_TERMS.search(f"{link} {title} {snippet}"):
                return ExtractedHiringSignal(
                    source="careers_page",
                    signal_type=HiringSignalType.CAREERS_PAGE,
                    source_url=link or None,
                    job_title=None,
                    location=ref.city,
                    posted_at=None,
                    description_excerpt=(snippet[:500] or "Company careers page detected."),
                    confidence_score=0.55,
                )
        return None

    # -- extract ------------------------------------------------------------- #

    async def extract(self, company: CompanyRef, ctx: SourceRunContext) -> ExtractionResult:
        """Attach Facebook hiring signals for one company.

        Order: mode 1 (authorized Page, if a credential exists) then mode 3
        (SERP jobs + careers fallback). With NO compliant access at all it audits
        a clear skip and returns an empty result — the job continues (spec §8).
        """
        unavailable = self.check_access(ctx)
        if unavailable is not None:
            ctx.audit(
                "facebook:access-check",
                status="skipped",
                error=unavailable.reason,
            )
            return ExtractionResult.empty()

        signals: list[ExtractedHiringSignal] = []

        # Mode 1: authorized Page read (only if the tenant has a stored credential).
        cred = self._page_credential(ctx)
        if cred is not None:
            fields = await self._read_authorized_page(cred, company, ctx)
            if fields:
                sig = self._signal_from_page_fields(fields, company)
                if sig is not None:
                    signals.append(sig)

        # Mode 3: hiring-signal fallback via approved SERP (jobs + careers).
        signals.extend(await self._serp_jobs_signals(company, ctx))
        careers = await self._careers_signal(company, ctx)
        if careers is not None:
            signals.append(careers)

        return ExtractionResult(hiring_signals=signals)


def _parse_posted_at(text: str | None) -> datetime | None:
    """Best-effort parse of SERP ``posted_at`` (e.g. "3 days ago") to a UTC time."""
    if not text:
        return None
    match = re.match(r"\s*(\d+)\s+(hour|day|week|month)s?\s+ago", text, re.IGNORECASE)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    now = datetime.now(UTC)
    delta = {
        "hour": timedelta(hours=amount),
        "day": timedelta(days=amount),
        "week": timedelta(weeks=amount),
        "month": timedelta(days=30 * amount),
    }[unit]
    return now - delta
