"""Batch-6 validation honesty: the job's validation_stages option is honored and
the seeded rule defaults are valid (no silent coercion).
"""

from __future__ import annotations

from app.models.settings_models import default_validation_rules
from app.pipeline.stages import _job_validation_stages
from app.pipeline.validation import RuleSet


class _Job:
    def __init__(self, totals_json):
        self.totals_json = totals_json


def test_job_validation_stages_parses_selection():
    job = _Job({"job_options": {"validation_stages": ["Syntax", "MX", "LLM"]}})
    assert _job_validation_stages(job) == frozenset({"syntax", "mx", "llm"})


def test_job_validation_stages_empty_means_all():
    assert _job_validation_stages(_Job(None)) == frozenset()
    assert _job_validation_stages(_Job({})) == frozenset()
    assert _job_validation_stages(_Job({"job_options": {}})) == frozenset()
    assert _job_validation_stages(_Job({"job_options": {"validation_stages": []}})) == frozenset()


def test_default_rules_seed_is_valid_without_coercion():
    seed = default_validation_rules()
    rules = RuleSet.from_dict(seed)
    # The seed must already BE what from_dict resolves to — no silent rewriting.
    assert seed["llm_mode"] == "advisory"
    assert rules.llm_mode == "advisory"
    assert rules.unknown_retry == {"max_attempts": 3, "delay_hours": 6}
    assert seed["unknown_retry"] == {"max_attempts": 3, "delay_hours": 6}
