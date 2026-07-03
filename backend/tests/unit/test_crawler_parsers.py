"""Unit tests for the website-crawler parsers (spec §8/§9 extraction techniques).

Pure and offline: every test feeds fixture HTML/text to a parser and asserts the
structured output. Covers the obfuscation decoder corpus (incl. Cloudflare
``data-cfemail`` hex), phone E.164 normalization, JSON-LD parsing, team-page
extraction, social-link classification, hiring-keyword detection, and protego
robots allow/deny. NO network is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from protego import Protego

from app.crawler.frontier import Frontier, registrable_domain, score_url
from app.crawler.parsers.emails import decode_cfemail, deobfuscate, extract_emails
from app.crawler.parsers.jsonld import parse_jsonld
from app.crawler.parsers.phones import extract_phones, region_for_country
from app.crawler.parsers.social import detect_hiring_signals, extract_social_links
from app.crawler.parsers.team_pages import classify_designation, extract_team_members
from app.crawler.robots import USER_AGENT

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site"


def _cfemail_encode(email: str, key: int = 0x3B) -> str:
    """Reference Cloudflare data-cfemail encoder (first byte = XOR key)."""
    out = format(key, "02x")
    for ch in email:
        out += format(ord(ch) ^ key, "02x")
    return out


# --------------------------------------------------------------------------- #
# Email obfuscation decoder corpus
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("jane [at] acme [dot] com", "jane@acme.com"),
        ("bob (at) foo dot io", "bob@foo.io"),
        ("carl {at} bar {dot} co", "carl@bar.co"),
        ("dev at example dot org", "dev@example.org"),
        ("hi&#64;acme.com", "hi@acme.com"),
        ("plain@already.com", "plain@already.com"),
    ],
)
def test_deobfuscate_corpus(raw, expected):
    assert deobfuscate(raw).strip() == expected


def test_extract_emails_from_obfuscated_text():
    text = "reach jane [at] acme [dot] com or info@acme.com, dev at foo dot io"
    got = extract_emails(text=text)
    assert "jane@acme.com" in got
    assert "info@acme.com" in got
    assert "dev@foo.io" in got


def test_decode_cfemail_roundtrip():
    for email in ("test@example.com", "managing.partner@acme-audit.example", "a@b.co"):
        assert decode_cfemail(_cfemail_encode(email)) == email


@pytest.mark.parametrize("bad", ["", "zz", "3b", "not-hex-at-all", "3b56xx"])
def test_decode_cfemail_rejects_garbage(bad):
    assert decode_cfemail(bad) is None


def test_extract_emails_mailto_and_cfemail():
    hexstr = _cfemail_encode("owner@acme.example")
    html = (
        '<a href="mailto:hi@acme.example?subject=x">mail</a>'
        f'<a class="__cf_email__" data-cfemail="{hexstr}">[email&#160;protected]</a>'
    )
    soup = BeautifulSoup(html, "lxml")
    got = extract_emails(html=html, soup=soup)
    assert "hi@acme.example" in got  # mailto, query stripped
    assert "owner@acme.example" in got  # cfemail decoded


# --------------------------------------------------------------------------- #
# Phone normalization
# --------------------------------------------------------------------------- #


def test_region_for_country():
    assert region_for_country("India") == "IN"
    assert region_for_country("in") == "IN"
    assert region_for_country("United States") == "US"
    assert region_for_country(None) is None


def test_extract_phones_india_national_format():
    text = "Call +91 79 4890 1234 or our Mumbai desk 022 2757 9191."
    got = extract_phones(text=text, country="India")
    assert "+917948901234" in got
    assert "+912227579191" in got


def test_extract_phones_from_tel_links():
    soup = BeautifulSoup('<a href="tel:+14155551234">call</a>', "lxml")
    got = extract_phones(soup=soup, country="United States")
    assert got == ["+14155551234"]


def test_extract_phones_rejects_junk():
    # A bare invalid sequence must not be emitted.
    got = extract_phones(text="order 1234 items, ref 000", country="India")
    assert got == []


# --------------------------------------------------------------------------- #
# JSON-LD parsing (arrays / @graph / ContactPoint / Person / JobPosting)
# --------------------------------------------------------------------------- #


def test_jsonld_graph_org_person_job():
    block = """
    {
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": ["Organization", "LocalBusiness"],
          "name": "Acme Audit LLP",
          "telephone": "+91 79 4890 1234",
          "email": "reception@acme-audit.example",
          "sameAs": ["https://linkedin.com/company/acme", "https://facebook.com/acme"],
          "description": "Chartered accountants in Ahmedabad.",
          "address": {"@type": "PostalAddress", "addressLocality": "Ahmedabad", "addressCountry": "IN"},
          "contactPoint": [{"@type": "ContactPoint", "telephone": "+91 22 2757 9191", "email": "support@acme-audit.example"}]
        },
        {"@type": "Person", "name": "Priya Sharma", "jobTitle": "Managing Partner",
         "email": "priya@acme-audit.example", "sameAs": ["https://linkedin.com/in/priya"]},
        {"@type": "JobPosting", "title": "Audit Associate", "datePosted": "2026-05-01",
         "description": "Join us", "url": "https://acme-audit.example/jobs/1"}
      ]
    }
    """
    result = parse_jsonld([block])
    assert result.name == "Acme Audit LLP"
    assert "reception@acme-audit.example" in result.emails
    assert "support@acme-audit.example" in result.emails  # from ContactPoint
    assert "+91 79 4890 1234" in result.phones
    assert "+91 22 2757 9191" in result.phones
    assert "https://linkedin.com/company/acme" in result.same_as
    assert result.address and "Ahmedabad" in result.address
    assert len(result.people) == 1
    assert result.people[0].name == "Priya Sharma"
    assert result.people[0].job_title == "Managing Partner"
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Audit Associate"
    assert result.jobs[0].date_posted is not None


def test_jsonld_tolerates_single_object_and_bad_block():
    good = '{"@type": "Organization", "name": "Solo Corp", "email": "hi@solo.example"}'
    result = parse_jsonld(["{ this is not json", good, ""])
    assert result.name == "Solo Corp"
    assert "hi@solo.example" in result.emails


# --------------------------------------------------------------------------- #
# Team-page extraction
# --------------------------------------------------------------------------- #


def test_extract_team_members_from_fixture():
    html = (FIXTURES / "team.html").read_text()
    soup = BeautifulSoup(html, "lxml")
    members = {m.name: m for m in extract_team_members(soup)}

    assert "Priya Sharma" in members
    assert members["Priya Sharma"].role_category == "partner"
    assert members["Priya Sharma"].seniority == "c_level"

    assert "Raj Mehta" in members
    # "Director of Audit" must classify as director, NOT executive (cto substring).
    assert members["Raj Mehta"].role_category == "director"

    assert "Anita Desai" in members
    assert members["Anita Desai"].role_category in ("founder", "executive")

    # A non-person card ("Ahmedabad Office" / "Head Office") is not a member.
    assert "Ahmedabad Office" not in members
    # Confidence is bounded and decision-makers score high.
    assert all(0.0 < m.confidence <= 0.95 for m in members.values())
    assert members["Priya Sharma"].confidence >= 0.8


def test_classify_designation_word_boundary():
    # 'director' must not be caught by the 'cto' acronym rule.
    assert classify_designation("Director of Audit") == ("senior", "director")
    assert classify_designation("CTO") == ("c_level", "executive")
    assert classify_designation("Our Leadership") is None


# --------------------------------------------------------------------------- #
# Social links + hiring signals
# --------------------------------------------------------------------------- #


def test_extract_social_links_business_only():
    html = """
    <a href="https://linkedin.com/company/acme">li company</a>
    <a href="https://www.facebook.com/acmefirm">fb page</a>
    <a href="https://facebook.com/sharer.php?u=x">share</a>
    <a href="https://twitter.com/acme">tw</a>
    """
    soup = BeautifulSoup(html, "lxml")
    links = extract_social_links(soup=soup)
    assert links["linkedin"] == "https://linkedin.com/company/acme"
    assert links["facebook"] == "https://www.facebook.com/acmefirm"
    # Facebook share/dialog links are excluded.
    assert "sharer" not in links.get("facebook", "")


def test_extract_social_links_from_jsonld_sameas():
    links = extract_social_links(
        extra_urls=["https://linkedin.com/company/foo", "https://facebook.com/foopage"]
    )
    assert links["linkedin"] == "https://linkedin.com/company/foo"
    assert links["facebook"] == "https://facebook.com/foopage"


def test_detect_hiring_signals():
    text = "About us. We're hiring senior auditors — join our team and see our open positions."
    hits = {phrase for phrase, _ in detect_hiring_signals(text)}
    assert "we're hiring" in hits
    assert "join our team" in hits
    assert "open positions" in hits
    # Every hit carries a snippet.
    assert all(snippet for _, snippet in detect_hiring_signals(text))


def test_no_hiring_signal_in_plain_text():
    assert detect_hiring_signals("We provide audit and tax services.") == []


# --------------------------------------------------------------------------- #
# Frontier scoring + same-domain filtering
# --------------------------------------------------------------------------- #


def test_score_url_priorities():
    assert score_url("https://x.com/contact") == 100
    assert score_url("https://x.com/about-us") == 90
    assert score_url("https://x.com/partners") == 85
    assert score_url("https://x.com/services") == 60
    assert score_url("https://x.com/careers") == 55
    assert score_url("https://x.com/privacy") == 40
    assert score_url("https://x.com/random-blog-post") == 0
    # Footer bonus only applies to an already-interesting link.
    assert score_url("https://x.com/privacy", in_footer=True) == 50
    assert score_url("https://x.com/random", in_footer=True) == 0


def test_registrable_domain():
    assert registrable_domain("https://blog.acme.co.uk/x") == "acme.co.uk"
    assert registrable_domain("https://www.acme.co.uk") == "acme.co.uk"
    assert registrable_domain("https://acme.com") == "acme.com"
    # Unknown/reserved TLD -> full host (so distinct hosts stay distinct).
    assert registrable_domain("http://a.example") == "a.example"
    assert registrable_domain("http://127.0.0.1:8080/x") == "127.0.0.1"


def test_frontier_same_domain_only():
    f = Frontier(seed_url="https://acme.com/")
    f.add_links(
        "https://acme.com/",
        [
            ("/contact", "Contact"),
            ("https://acme.com/about", "About"),
            ("https://other-firm.com/partner", "Partner"),  # off-domain -> dropped
            ("mailto:x@acme.com", "mail"),  # non-http -> dropped
            ("https://blog.acme.com/post", "Blog"),  # same registrable domain
        ],
    )
    urls = {link.url for link in f.top(10)}
    assert "https://acme.com/contact" in urls
    assert "https://acme.com/about" in urls
    assert "https://blog.acme.com/post" in urls  # subdomain collapses to eTLD+1
    assert not any("other-firm.com" in u for u in urls)
    assert not any(u.startswith("mailto") for u in urls)
    # Highest-scoring (contact=100) is first.
    assert f.top(1)[0].url == "https://acme.com/contact"


# --------------------------------------------------------------------------- #
# robots allow/deny (protego)
# --------------------------------------------------------------------------- #


def test_protego_allow_deny():
    body = "User-agent: *\nDisallow: /private/\nCrawl-delay: 3\n"
    parser = Protego.parse(body)
    assert parser.can_fetch("https://acme.example/team", USER_AGENT)
    assert not parser.can_fetch("https://acme.example/private/secret", USER_AGENT)
    assert parser.crawl_delay(USER_AGENT) == 3


def test_robots_policy_from_body_allow_deny_and_delay_cap():
    from app.crawler.robots import _policy_from_body

    policy = _policy_from_body(
        "User-agent: *\nDisallow: /private/\nCrawl-delay: 999\n", "acme.example"
    )
    assert policy.allowed("https://acme.example/team")
    assert not policy.allowed("https://acme.example/private/x")
    # Crawl-delay is capped at 10s so a hostile robots file can't stall a job.
    assert policy.crawl_delay == 10.0


def test_robots_missing_or_empty_allows_all():
    from app.crawler.robots import _policy_from_body

    policy = _policy_from_body("", "acme.example")  # no robots => allow all
    assert policy.allowed("https://acme.example/anything")
    assert policy.crawl_delay is None
