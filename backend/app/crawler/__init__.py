"""Real website crawler + extraction (spec §8 Company Websites, §9 Contacts).

Tiered async fetch (httpx -> Playwright fallback), robots.txt honoring, a
keyword-scored frontier over same-registrable-domain links, and a set of
tolerant HTML parsers (emails/phones/JSON-LD/team pages/social + hiring
signals). ``extract.crawl_company`` assembles per-page partials into one
``ExtractionResult`` for the CompanyWebsitesAdapter.
"""
