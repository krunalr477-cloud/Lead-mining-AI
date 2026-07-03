"""Dedupe keys + merge semantics (spec §9)."""

from app.pipeline.dedupe import (
    SourceEvidence,
    company_dedupe_key,
    contact_dedupe_key,
    merge_company_evidence,
    merge_contact,
    normalize_domain,
    normalize_phone,
    slug_name,
)

# --------------------------------------------------------------------------- #
# normalizers
# --------------------------------------------------------------------------- #


def test_normalize_domain_strips_www_scheme_path():
    assert normalize_domain("https://www.Acme.com/team?x=1") == "acme.com"
    assert normalize_domain("http://acme.com:8080/") == "acme.com"
    assert normalize_domain("someone@acme.com") == "acme.com"
    assert normalize_domain("WWW.ACME.COM") == "acme.com"
    assert normalize_domain(None) is None
    assert normalize_domain("") is None


def test_normalize_phone_e164ish():
    a = normalize_phone("+1 (415) 555-2671")
    b = normalize_phone("+14155552671")
    assert a == b == "+14155552671"


def test_normalize_phone_fallback_digits():
    # Not a valid/parseable number; fallback keeps digits (+ prefix preserved).
    assert normalize_phone("079-1234-5678") == "07912345678"
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_slug_name_drops_suffixes_and_accents():
    assert slug_name("Acme Consulting, LLC") == "acme-consulting"
    assert slug_name("The Näme Co.") == "name"
    assert slug_name("Acme Inc") == "acme"
    assert slug_name(None) is None


# --------------------------------------------------------------------------- #
# company dedupe key — domain vs name vs phone
# --------------------------------------------------------------------------- #


def test_same_company_via_domain():
    k1 = company_dedupe_key(
        "Acme Consulting LLC", "https://www.acme.com", "+1 415 555 2671", "1 Main St"
    )
    k2 = company_dedupe_key(
        "Acme Consulting, L.L.C.", "acme.com/contact", "(415) 555-2671", "1 Main Street"
    )
    assert k1 == k2 == "domain:acme.com"


def test_same_company_via_name_when_no_domain():
    k1 = company_dedupe_key("Acme Consulting LLC", None, "+14155552671", "1 Main St")
    k2 = company_dedupe_key("Acme Consulting, Inc", None, "+14155559999", "99 Other Rd")
    assert k1 == k2 == "name:acme-consulting"


def test_same_company_via_phone_when_no_domain_or_name():
    k1 = company_dedupe_key(None, None, "+1 415 555 2671", None)
    k2 = company_dedupe_key(None, None, "+14155552671", None)
    assert k1 == k2 == "phone:+14155552671"


def test_different_companies_do_not_collide():
    k1 = company_dedupe_key("Acme Consulting", "acme.com", "+14155552671", None)
    k2 = company_dedupe_key("Beta Advisory", "beta.io", "+14155559999", None)
    assert k1 != k2


def test_domain_key_never_collides_with_phone_key():
    # Namespacing prevents a name/phone/addr key from ever matching a domain key.
    dom = company_dedupe_key(None, "acme.com", None, None)
    phone = company_dedupe_key(None, None, "acme.com", None)  # nonsense phone -> digits empty
    assert dom == "domain:acme.com"
    assert phone != dom


def test_company_key_none_when_nothing_usable():
    assert company_dedupe_key(None, None, None, None) is None


# --------------------------------------------------------------------------- #
# contact dedupe key
# --------------------------------------------------------------------------- #


def test_contact_via_email():
    k1 = contact_dedupe_key("John.Doe@acme.com", "John Doe", "co-1")
    k2 = contact_dedupe_key("john.doe@acme.com", "J. Doe", "co-2")
    assert k1 == k2 == "email:john.doe@acme.com"


def test_contact_via_name_scoped_to_company():
    k1 = contact_dedupe_key(None, "John Doe", "co-1")
    k2 = contact_dedupe_key(None, "John Doe", "co-1")
    assert k1 == k2 == "name:co-1:john-doe"


def test_contact_same_name_different_company_distinct():
    k1 = contact_dedupe_key(None, "John Doe", "co-1")
    k2 = contact_dedupe_key(None, "John Doe", "co-2")
    assert k1 != k2


def test_contact_key_none_without_email_or_company():
    assert contact_dedupe_key(None, "John Doe", None) is None
    assert contact_dedupe_key(None, None, "co-1") is None


# --------------------------------------------------------------------------- #
# merge semantics
# --------------------------------------------------------------------------- #


def test_merge_company_fill_only_and_evidence():
    existing = {"canonical_name": "Acme", "website": None, "source_urls": ["u1"]}
    incoming = {"canonical_name": "Acme Corp", "website": "acme.com", "source_urls": ["u2"]}
    ev = SourceEvidence(
        source_name="google_maps",
        source_url="u3",
        access_method="official_api",
        compliance_posture="green",
    )
    res = merge_company_evidence(existing, incoming, ev)

    # Existing non-empty name preserved; empty website filled.
    assert "canonical_name" not in res.fields  # unchanged
    assert res.fields["website"] == "acme.com"
    assert res.evidence == [ev]
    assert res.merged_source_urls == ["u1", "u2", "u3"]


def test_merge_contact_fill_only_confidence_max_and_new_email():
    existing = {
        "full_name": "John Doe",
        "email": "john@acme.com",
        "designation": None,
        "confidence_score": 0.8,
    }
    incoming = {
        "full_name": "J. Doe",
        "email": "j.doe@acme.com",
        "designation": "Partner",
        "confidence_score": 0.9,
    }
    res = merge_contact(existing, incoming)

    assert res.fields["designation"] == "Partner"  # filled
    assert "full_name" not in res.fields  # preserved
    assert res.fields["confidence_score"] == 0.9  # max
    assert "email" not in res.fields  # existing email kept
    assert res.new_email_candidates == ["j.doe@acme.com"]  # surfaced as candidate


def test_merge_contact_fills_empty_email():
    existing = {"email": None}
    incoming = {"email": "new@acme.com"}
    res = merge_contact(existing, incoming)
    assert res.fields["email"] == "new@acme.com"
    assert res.new_email_candidates == []
