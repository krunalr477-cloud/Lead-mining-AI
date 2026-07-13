"""URL hygiene: which URLs are NOT a company's own website.

Google Places sometimes lists a social profile, messenger link, link hub, or
directory listing as a business's ``websiteUri``. Persisting those poisons the
pipeline: linkedin.com robots-blocks the crawler (false 'unreachable'), the
dedupe domain becomes linkedin.com, and validation runs against the wrong
domain. ``is_non_company_website`` REJECTS such URLs — nothing here fetches
them (this module deliberately lives outside app/adapters so the compliance
guard, which forbids real adapters from *targeting* social endpoints, keeps
its teeth).
"""

from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["NON_COMPANY_WEBSITE_HOSTS", "is_non_company_website"]

# Matched by exact host or suffix (subdomains included).
NON_COMPANY_WEBSITE_HOSTS: frozenset[str] = frozenset(
    {
        "linkedin.com",
        "facebook.com",
        "m.facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "youtu.be",
        "wa.me",
        "api.whatsapp.com",
        "chat.whatsapp.com",
        "linktr.ee",
        "t.me",
        "justdial.com",
        "sulekha.com",
        "indiamart.com",
        "google.com",
    }
)


def is_non_company_website(url: str | None) -> bool:
    """True when ``url``'s host is a social/profile/directory host that can
    never be the company's own site."""
    if not url:
        return False
    candidate = url if "//" in url else f"//{url}"
    host = (urlsplit(candidate).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in NON_COMPANY_WEBSITE_HOSTS)
