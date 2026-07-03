"""Crawl frontier (spec §8 page prioritization).

Start at the homepage, collect same-registrable-domain links (compared via
``tldextract`` so ``blog.acme.co.uk`` and ``www.acme.co.uk`` share a domain but
``acme-partner.com`` does not), and score each by the keywords in its
URL/anchor text. The adapter then crawls the top-N by score. Scoring mirrors the
spec's page priorities: Contact 100, About/Team/Leadership/People 90,
Partners/Management 85, Services 60, Careers/Jobs 55, Privacy/Imprint 40; a
footer link gets +10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import tldextract

__all__ = ["ScoredLink", "Frontier", "registrable_domain", "score_url"]

# (keywords, score) — checked in order; first hit sets the base score.
_KEYWORD_SCORES: list[tuple[tuple[str, ...], int]] = [
    (("contact", "contact-us", "contactus", "reach-us", "get-in-touch"), 100),
    (("about", "about-us", "team", "our-team", "leadership", "people", "our-people"), 90),
    (("partners", "management", "board", "directors"), 85),
    (("services", "solutions", "practice", "expertise", "what-we-do"), 60),
    (("careers", "career", "jobs", "join-us", "vacancies", "openings"), 55),
    (("privacy", "imprint", "impressum", "legal", "terms"), 40),
]

_MAX_SCORE = 200


def registrable_domain(url: str) -> str:
    """Registrable (eTLD+1) domain of a URL, lower-cased. '' if unparseable.

    For hosts whose TLD is not in the public-suffix list (an IP address, a
    ``localhost``, or a reserved TLD like ``.example``/``.test``), there is no
    real eTLD+1, so we fall back to the FULL host — this keeps two distinct
    unknown-TLD hosts (``a.example`` vs ``b.example``) from being treated as the
    same domain during same-domain frontier filtering.
    """
    ext = tldextract.extract(url)
    if ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    # No known public suffix: use the full registered host (fqdn), or the raw
    # netloc host for IPs / bare hostnames (e.g. 127.0.0.1).
    fqdn = ext.fqdn
    if fqdn:
        return fqdn.lower()
    host = urlparse(url if "//" in url else f"//{url}").hostname or ""
    return host.lower()


def score_url(url: str, anchor_text: str = "", *, in_footer: bool = False) -> int:
    """Keyword score for a candidate link (0 = uninteresting)."""
    haystack = f"{url} {anchor_text}".lower()
    base = 0
    for keywords, points in _KEYWORD_SCORES:
        if any(kw in haystack for kw in keywords):
            base = points
            break
    if in_footer and base > 0:
        base += 10
    return min(base, _MAX_SCORE)


@dataclass(slots=True)
class ScoredLink:
    url: str
    score: int
    anchor: str = ""


@dataclass
class Frontier:
    """Same-domain link collector + scorer, seeded from a homepage URL."""

    seed_url: str
    domain: str = ""
    _seen: set[str] = field(default_factory=set)
    _links: dict[str, ScoredLink] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.domain:
            self.domain = registrable_domain(self.seed_url)
        self._seen.add(self._canon(self.seed_url))

    @staticmethod
    def _canon(url: str) -> str:
        """Normalize for de-dup: drop fragment + trailing slash, lower host."""
        url, _ = urldefrag(url)
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        host = parsed.netloc.lower()
        return f"{parsed.scheme}://{host}{path}{('?' + parsed.query) if parsed.query else ''}"

    def add_links(
        self, base_url: str, links: list[tuple[str, str]], *, in_footer: bool = False
    ) -> None:
        """Add (href, anchor_text) pairs discovered on ``base_url``.

        Non-http(s) schemes, off-domain links, and already-seen URLs are dropped.
        A link's best (highest) score across occurrences is kept.
        """
        for href, anchor in links:
            if not href:
                continue
            href = href.strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if registrable_domain(absolute) != self.domain:
                continue
            canon = self._canon(absolute)
            if canon in self._seen:
                continue
            score = score_url(absolute, anchor, in_footer=in_footer)
            existing = self._links.get(canon)
            if existing is None or score > existing.score:
                self._links[canon] = ScoredLink(url=absolute, score=score, anchor=anchor)

    def top(self, limit: int) -> list[ScoredLink]:
        """Highest-scoring unvisited links, best first (stable by URL)."""
        ranked = sorted(self._links.values(), key=lambda link: (-link.score, link.url))
        return ranked[:limit]

    def mark_visited(self, url: str) -> None:
        canon = self._canon(url)
        self._seen.add(canon)
        self._links.pop(canon, None)

    def visited(self, url: str) -> bool:
        return self._canon(url) in self._seen
