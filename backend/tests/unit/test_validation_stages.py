"""Stage functions: syntax, disposable, role-based, MX (with a mock resolver)."""

import dns.exception
import dns.resolver
import pytest

from app.constants import StageStatus
from app.pipeline.validation import (
    RuleSet,
    ValidationTransient,
    check_disposable,
    check_mx,
    check_syntax,
    is_role_based,
)

# --------------------------------------------------------------------------- #
# Stage 1 — syntax
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "email",
    ["john.doe@example.com", "a@b.co", "first+tag@sub.domain.io", "Name.Surname@company.co.uk"],
)
def test_syntax_valid(email):
    assert check_syntax(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "",
        "  ",
        "not-an-email",
        "john@",
        "@example.com",
        "a@@b.com",
        "john doe@example.com",
        None,
        "plainaddress",
    ],
)
def test_syntax_malformed(email):
    assert check_syntax(email) is False


# --------------------------------------------------------------------------- #
# Stage 2 — disposable
# --------------------------------------------------------------------------- #


def test_disposable_known_throwaway_rejected():
    # mailinator.com is in the maintained blocklist.
    assert check_disposable("someone@mailinator.com") is True


def test_disposable_real_domain_ok():
    assert check_disposable("someone@example.com") is False


def test_disposable_extra_domains():
    assert check_disposable("x@throwaway.test", extra_domains={"throwaway.test"}) is True
    assert check_disposable("x@throwaway.test") is False


def test_disposable_case_and_dot_insensitive():
    assert check_disposable("x@MailInator.CoM") is True
    assert check_disposable("x@custom.bad", extra_domains={"CUSTOM.BAD"}) is True


def test_disposable_unparseable_is_not_disposable():
    # Syntax stage owns malformed rejection; disposable stage stays silent.
    assert check_disposable("no-at-sign") is False


# --------------------------------------------------------------------------- #
# Stage 3 — role-based
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "email",
    [
        "info@acme.com",
        "sales@acme.com",
        "SUPPORT@acme.com",
        "hr@acme.com",
        "careers@acme.com",
        "jobs.eu@acme.com",
        "sales+us@acme.com",
        "hello@acme.com",
    ],
)
def test_role_based_matches(email):
    assert is_role_based(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "john@acme.com",
        "j.doe@acme.com",
        "salesforce@acme.com",
        "priyanka@acme.com",
        "info.rmatics@acme.com".replace("info.rmatics", "informatics"),
    ],  # informatics@ not role
)
def test_role_based_non_matches(email):
    assert is_role_based(email) is False


def test_role_based_custom_keywords():
    assert is_role_based("billing@acme.com", role_keywords=["billing"]) is True
    assert is_role_based("info@acme.com", role_keywords=["billing"]) is False


def test_role_based_empty_keywords_never_matches():
    assert is_role_based("info@acme.com", role_keywords=[]) is False


def test_role_based_malformed_email():
    assert is_role_based("not-an-email") is False
    assert is_role_based("@acme.com") is False


# --------------------------------------------------------------------------- #
# Stage 4 — MX (mock resolver)
# --------------------------------------------------------------------------- #


class _MockExchange:
    def __init__(self, host):
        self.exchange = host

    def __str__(self):
        return str(self.exchange)


class _MockAnswer:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)

    def __len__(self):
        return len(self._records)


class MockResolver:
    """Programmable resolver: map (domain, rdtype) -> answer list or an exception."""

    def __init__(self, responses):
        self._responses = responses

    def resolve(self, qname, rdtype):
        key = (qname, rdtype)
        if key not in self._responses:
            raise dns.resolver.NoAnswer
        result = self._responses[key]
        if isinstance(result, Exception) or (
            isinstance(result, type) and issubclass(result, Exception)
        ):
            raise result
        return _MockAnswer(result)


def test_mx_present_passes():
    resolver = MockResolver({("acme.com", "MX"): [_MockExchange("mail.acme.com.")]})
    status, detail = check_mx("acme.com", resolver=resolver)
    assert status is StageStatus.PASS
    assert "mail.acme.com" in detail


def test_mx_a_fallback_passes():
    # No MX rrset, but the domain has an A record -> implicit MX, PASS.
    resolver = MockResolver(
        {("acme.com", "MX"): dns.resolver.NoAnswer, ("acme.com", "A"): ["1.2.3.4"]}
    )
    status, detail = check_mx("acme.com", resolver=resolver)
    assert status is StageStatus.PASS
    assert "fallback" in detail.lower()


def test_mx_nxdomain_fails():
    resolver = MockResolver({("nope.invalid", "MX"): dns.resolver.NXDOMAIN})
    status, detail = check_mx("nope.invalid", resolver=resolver)
    assert status is StageStatus.FAIL
    assert "NXDOMAIN" in detail


def test_mx_no_answer_no_address_fails():
    # No MX, no A, no AAAA -> FAIL (not transient).
    resolver = MockResolver({})  # every lookup -> NoAnswer
    status, _ = check_mx("empty.example", resolver=resolver)
    assert status is StageStatus.FAIL


def test_mx_timeout_raises_transient():
    resolver = MockResolver({("slow.example", "MX"): dns.exception.Timeout})
    with pytest.raises(ValidationTransient):
        check_mx("slow.example", resolver=resolver)


def test_mx_servfail_raises_transient():
    resolver = MockResolver({("brk.example", "MX"): dns.resolver.NoNameservers})
    with pytest.raises(ValidationTransient):
        check_mx("brk.example", resolver=resolver)


def test_mx_empty_domain_fails():
    status, _ = check_mx("", resolver=MockResolver({}))
    assert status is StageStatus.FAIL


def test_mx_strips_trailing_dot_and_case():
    resolver = MockResolver({("acme.com", "MX"): [_MockExchange("mx.acme.com.")]})
    status, _ = check_mx("ACME.com.", resolver=resolver)
    assert status is StageStatus.PASS


# --------------------------------------------------------------------------- #
# RuleSet loading
# --------------------------------------------------------------------------- #


def test_ruleset_defaults():
    rs = RuleSet.from_dict(None)
    assert rs.llm_threshold == 0.55
    assert rs.llm_mode == "advisory"
    assert rs.allow_role_based is False
    assert rs.catch_all_policy == "review"
    assert rs.risk_policy == "review"
    assert rs.unknown_retry == {"max_attempts": 3, "delay_hours": 6}
    assert "info" in rs.role_keywords


def test_ruleset_garbage_falls_back():
    rs = RuleSet.from_dict(
        {
            "llm_threshold": "banana",
            "llm_mode": "adjudicate",  # not a recognized mode -> advisory
            "catch_all_policy": "nonsense",
            "risk_policy": "explode",
            "role_keywords": [],
        }
    )
    assert rs.llm_threshold == 0.55
    assert rs.llm_mode == "advisory"
    assert rs.catch_all_policy == "review"
    assert rs.risk_policy == "review"
    assert rs.role_keywords  # fell back to defaults


def test_ruleset_threshold_clamped():
    assert RuleSet.from_dict({"llm_threshold": 5}).llm_threshold == 1.0
    assert RuleSet.from_dict({"llm_threshold": -3}).llm_threshold == 0.0


def test_ruleset_unknown_retry_int_backcompat():
    # ValidationRuleSet seeds a bare int; treat as max_attempts.
    rs = RuleSet.from_dict({"unknown_retry": 5})
    assert rs.unknown_retry["max_attempts"] == 5
    assert rs.unknown_retry["delay_hours"] == 6
