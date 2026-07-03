"""Truth table for decide(): all 11 FinalEmailStatus outcomes + policy permutations."""

import pytest

from app.constants import FinalEmailStatus, MillionVerifierStatus, StageStatus
from app.pipeline.validation import RuleSet, decide

PASS = StageStatus.PASS
FAIL = StageStatus.FAIL
MV = MillionVerifierStatus


def _base(**overrides):
    """All hard gates passing, MV valid — the canonical VERIFIED input."""
    kwargs = dict(
        syntax_ok=True,
        disposable_ok=True,
        role_based=False,
        mx_status=PASS,
        llm_score=0.9,
        mv_status=MV.VALID,
        suppressed=False,
        rules=RuleSet.from_dict({}),
    )
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------------- #
# All 11 final statuses reachable
# --------------------------------------------------------------------------- #


def test_verified_happy_path():
    status, reason = decide(**_base())
    assert status is FinalEmailStatus.VERIFIED
    assert reason


def test_suppressed_wins_over_everything():
    # Every other signal is also failing; suppression must still win.
    status, _ = decide(
        **_base(
            suppressed=True,
            syntax_ok=False,
            disposable_ok=False,
            role_based=True,
            mx_status=FAIL,
            mv_status=MV.INVALID,
        )
    )
    assert status is FinalEmailStatus.SUPPRESSED


def test_invalid_syntax():
    status, _ = decide(**_base(syntax_ok=False))
    assert status is FinalEmailStatus.INVALID_SYNTAX


def test_syntax_beats_disposable():
    status, _ = decide(**_base(syntax_ok=False, disposable_ok=False))
    assert status is FinalEmailStatus.INVALID_SYNTAX


def test_disposable_rejected():
    status, _ = decide(**_base(disposable_ok=False))
    assert status is FinalEmailStatus.DISPOSABLE_REJECTED


def test_disposable_beats_role_and_mx():
    status, _ = decide(**_base(disposable_ok=False, role_based=True, mx_status=FAIL))
    assert status is FinalEmailStatus.DISPOSABLE_REJECTED


def test_role_based_rejected_by_default():
    status, _ = decide(**_base(role_based=True))
    assert status is FinalEmailStatus.ROLE_BASED_REJECTED


def test_role_based_allowed_passes_through():
    rules = RuleSet.from_dict({"allow_role_based": True})
    status, _ = decide(**_base(role_based=True, rules=rules))
    assert status is FinalEmailStatus.VERIFIED


def test_role_based_beats_mx_fail():
    status, _ = decide(**_base(role_based=True, mx_status=FAIL))
    assert status is FinalEmailStatus.ROLE_BASED_REJECTED


def test_mx_failed():
    status, _ = decide(**_base(mx_status=FAIL))
    assert status is FinalEmailStatus.MX_FAILED


@pytest.mark.parametrize(
    "non_fail", [StageStatus.PENDING, StageStatus.SKIPPED, StageStatus.REVIEW, PASS]
)
def test_mx_non_fail_never_triggers_mx_failed(non_fail):
    status, _ = decide(**_base(mx_status=non_fail))
    assert status is FinalEmailStatus.VERIFIED


def test_provider_invalid():
    status, _ = decide(**_base(mv_status=MV.INVALID))
    assert status is FinalEmailStatus.PROVIDER_INVALID


def test_catch_all_review_default():
    status, _ = decide(**_base(mv_status=MV.CATCH_ALL))
    assert status is FinalEmailStatus.CATCH_ALL_REVIEW


def test_risk_review_default():
    status, _ = decide(**_base(mv_status=MV.RISK))
    assert status is FinalEmailStatus.RISK_REVIEW


def test_unknown_retry():
    status, _ = decide(**_base(mv_status=MV.UNKNOWN))
    assert status is FinalEmailStatus.UNKNOWN_RETRY


def test_all_eleven_statuses_covered():
    """Sanity: the tests above collectively reach every FinalEmailStatus."""
    reached = {
        decide(**_base())[0],
        decide(**_base(suppressed=True))[0],
        decide(**_base(syntax_ok=False))[0],
        decide(**_base(disposable_ok=False))[0],
        decide(**_base(role_based=True))[0],
        decide(**_base(mx_status=FAIL))[0],
        decide(**_base(rules=RuleSet.from_dict({"llm_mode": "hard"}), llm_score=0.1))[0],
        decide(**_base(mv_status=MV.INVALID))[0],
        decide(**_base(mv_status=MV.CATCH_ALL))[0],
        decide(**_base(mv_status=MV.RISK))[0],
        decide(**_base(mv_status=MV.UNKNOWN))[0],
    }
    assert reached == set(FinalEmailStatus)


# --------------------------------------------------------------------------- #
# LLM modes
# --------------------------------------------------------------------------- #


def test_llm_advisory_never_rejects_even_below_threshold():
    rules = RuleSet.from_dict({"llm_mode": "advisory", "llm_threshold": 0.55})
    status, _ = decide(**_base(rules=rules, llm_score=0.01))
    assert status is FinalEmailStatus.VERIFIED


def test_llm_hard_rejects_below_threshold():
    rules = RuleSet.from_dict({"llm_mode": "hard", "llm_threshold": 0.55})
    status, _ = decide(**_base(rules=rules, llm_score=0.30))
    assert status is FinalEmailStatus.LLM_LOW_CONFIDENCE


def test_llm_hard_passes_at_threshold_boundary():
    # score == threshold is NOT below threshold -> passes.
    rules = RuleSet.from_dict({"llm_mode": "hard", "llm_threshold": 0.55})
    status, _ = decide(**_base(rules=rules, llm_score=0.55))
    assert status is FinalEmailStatus.VERIFIED


def test_llm_hard_none_score_does_not_reject():
    rules = RuleSet.from_dict({"llm_mode": "hard", "llm_threshold": 0.55})
    status, _ = decide(**_base(rules=rules, llm_score=None))
    assert status is FinalEmailStatus.VERIFIED


def test_llm_hard_beats_mv_mapping():
    # LLM low confidence has higher precedence than the MV stage.
    rules = RuleSet.from_dict({"llm_mode": "hard", "llm_threshold": 0.55})
    status, _ = decide(**_base(rules=rules, llm_score=0.1, mv_status=MV.VALID))
    assert status is FinalEmailStatus.LLM_LOW_CONFIDENCE


# --------------------------------------------------------------------------- #
# catch_all / risk policies
# --------------------------------------------------------------------------- #


def test_catch_all_allow_policy_verifies():
    rules = RuleSet.from_dict({"catch_all_policy": "allow"})
    status, _ = decide(**_base(mv_status=MV.CATCH_ALL, rules=rules))
    assert status is FinalEmailStatus.VERIFIED


def test_risk_reject_policy_marks_provider_invalid():
    rules = RuleSet.from_dict({"risk_policy": "reject"})
    status, _ = decide(**_base(mv_status=MV.RISK, rules=rules))
    assert status is FinalEmailStatus.PROVIDER_INVALID


def test_risk_review_policy_marks_review():
    rules = RuleSet.from_dict({"risk_policy": "review"})
    status, _ = decide(**_base(mv_status=MV.RISK, rules=rules))
    assert status is FinalEmailStatus.RISK_REVIEW


# --------------------------------------------------------------------------- #
# MV skipped (None) — earlier gates decide
# --------------------------------------------------------------------------- #


def test_mv_none_verifies_when_gates_pass():
    status, _ = decide(**_base(mv_status=None))
    assert status is FinalEmailStatus.VERIFIED


def test_mv_none_still_respects_hard_gates():
    status, _ = decide(**_base(mv_status=None, mx_status=FAIL))
    assert status is FinalEmailStatus.MX_FAILED
