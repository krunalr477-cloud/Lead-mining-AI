"""Batch-2 contact-extraction quality gates (spec §9).

Covers the defects observed in the first real run: template/UI/service phrases
parsed as people, every email tagged role_inbox, blank person-email names, and no
exclude-keyword filtering.
"""

from __future__ import annotations

import pytest

from app.crawler.extract import _mint_role_contacts
from app.crawler.parsers.names import derive_name_from_local, is_plausible_person_name
from app.pipeline.stages import _contact_excluded, _extraction_rank


@pytest.mark.parametrize(
    "name, ok",
    [
        ("Derek Johnson", True),
        ("M.A. Rubin", True),
        ("Thomas Ferguson", True),
        ("Jean-Luc Picard", True),
        # junk seen in the real run
        ("Template", False),
        ("boilerplatetem", False),
        ("Learn More", False),
        ("Outsourced Controller Services", False),
        ("Traditional Accounting", False),
        ("Tax Planning", False),
        ("Cole & Associates", False),
        ("", False),
        (None, False),
        ("A", False),
        ("this is a very long string that is clearly not a persons name at all here", False),
    ],
)
def test_is_plausible_person_name(name, ok):
    assert is_plausible_person_name(name) is ok


@pytest.mark.parametrize(
    "local, expected",
    [
        ("derek.johnson", ("Derek Johnson", "Derek", "Johnson")),
        ("will_aderholt", ("Will Aderholt", "Will", "Aderholt")),
        ("info", None),
        ("sales", None),
        ("j", None),
        ("first.middle.last", None),  # 3 parts — ambiguous, skip
    ],
)
def test_derive_name_from_local(local, expected):
    assert derive_name_from_local(local) == expected


def test_mint_role_contacts_labels_and_names():
    emails = [
        "info@acme.com",  # role inbox
        "careers@acme.com",  # role inbox
        "derek.johnson@acme.com",  # person, derivable
        "paul@acme.com",  # person, single token (no derivation)
    ]
    out = {c.email: c for c in _mint_role_contacts(emails, "acme.com", "https://acme.com")}

    assert out["info@acme.com"].role_category == "role_inbox"
    assert out["careers@acme.com"].role_category == "role_inbox"

    derek = out["derek.johnson@acme.com"]
    assert derek.role_category is None  # NOT mislabeled role_inbox
    assert derek.full_name == "Derek Johnson"
    assert derek.first_name == "Derek" and derek.last_name == "Johnson"

    paul = out["paul@acme.com"]
    assert paul.role_category is None
    assert paul.full_name is None  # single-token local — no fabricated name

    # A real person email must outrank a role inbox.
    assert derek.confidence_score > out["info@acme.com"].confidence_score


class _EC:
    def __init__(
        self,
        full_name=None,
        designation=None,
        role_category=None,
        email=None,
        seniority=None,
        confidence_score=0.5,
    ):
        self.full_name = full_name
        self.designation = designation
        self.role_category = role_category
        self.email = email
        self.seniority = seniority
        self.confidence_score = confidence_score


def test_contact_excluded():
    kw = ["careers", "jobs", "hr", "intern"]
    assert _contact_excluded(_EC(email="careers@x.com"), kw) is True
    assert _contact_excluded(_EC(designation="HR Manager"), kw) is True
    assert _contact_excluded(_EC(full_name="Jane Intern"), kw) is True
    assert (
        _contact_excluded(_EC(email="derek.johnson@x.com", full_name="Derek Johnson"), kw) is False
    )
    assert _contact_excluded(_EC(email="anyone@x.com"), []) is False


def test_extraction_rank_prefers_decision_makers_with_email():
    partner = _EC(
        full_name="Amy Partner", role_category="partner", email="amy@x.com", confidence_score=0.7
    )
    role_inbox = _EC(role_category="role_inbox", email="info@x.com", confidence_score=0.4)
    plain_email = _EC(email="bob@x.com", confidence_score=0.68)
    ranked = sorted([role_inbox, plain_email, partner], key=_extraction_rank, reverse=True)
    assert ranked[0] is partner  # decision-maker with email ranks first
    assert ranked[-1] is role_inbox  # role inbox ranks last
