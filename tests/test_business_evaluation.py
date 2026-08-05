from collections import Counter
from pathlib import Path
import re

from retail_analytics_agent.business_evaluation import (
    EvaluationCategory,
    EvaluationSplit,
    ExpectedOutcome,
    load_business_evaluation_suite,
)


EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
DEVELOPMENT_PATH = EVALUATION_ROOT / "business_development.json"
HOLDOUT_PATH = EVALUATION_ROOT / "business_holdout.json"


def _load_suites():
    return (
        load_business_evaluation_suite(DEVELOPMENT_PATH),
        load_business_evaluation_suite(HOLDOUT_PATH),
    )


def _normalize_question(question: str) -> str:
    return re.sub(r"[\s，。！？、,.!?]", "", question).casefold()


def test_business_evaluation_has_40_development_and_20_holdout_cases() -> None:
    development, holdout = _load_suites()

    assert development.split is EvaluationSplit.DEVELOPMENT
    assert holdout.split is EvaluationSplit.HOLDOUT
    assert len(development.cases) == 40
    assert len(holdout.cases) == 20
    assert development.frozen is False
    assert holdout.frozen is True


def test_business_evaluation_has_fixed_snapshot_contract() -> None:
    development, holdout = _load_suites()

    for suite in (development, holdout):
        assert suite.dataset_version == "v1"
        assert suite.reference_time.isoformat() == "2026-08-16T12:00:00+08:00"
        assert suite.timezone == "Asia/Shanghai"
        assert suite.seed_snapshot_id == "retail-demo-evaluation-2026-08-16-v1"


def test_business_evaluation_has_required_category_distribution() -> None:
    development, holdout = _load_suites()
    counts = Counter(case.category for case in (*development.cases, *holdout.cases))

    assert counts == {
        EvaluationCategory.BASIC_ANALYSIS: 15,
        EvaluationCategory.COMPLEX_ANALYSIS: 15,
        EvaluationCategory.UNSUPPORTED: 10,
        EvaluationCategory.ACCESS_CONTROL: 10,
        EvaluationCategory.RESILIENCE: 10,
    }


def test_case_ids_are_unique_and_holdout_questions_do_not_leak() -> None:
    development, holdout = _load_suites()
    all_cases = (*development.cases, *holdout.cases)

    assert len({case.case_id for case in all_cases}) == len(all_cases)
    development_questions = {
        _normalize_question(case.question) for case in development.cases
    }
    holdout_questions = {
        _normalize_question(case.question) for case in holdout.cases
    }
    assert development_questions.isdisjoint(holdout_questions)


def test_trusted_results_have_human_gold_and_exact_expected_rows() -> None:
    development, holdout = _load_suites()
    trusted_outcomes = {
        ExpectedOutcome.SUCCEEDED,
        ExpectedOutcome.DEGRADED,
    }

    for case in (*development.cases, *holdout.cases):
        if case.expected_outcome in trusted_outcomes:
            assert case.expected_plan is not None
            assert case.expected_source_ids
            assert case.gold_sql is not None
            assert case.gold_sql.lstrip().upper().startswith("SELECT")
        else:
            assert case.gold_sql is None
            assert case.expected_rows == ()


def test_non_success_cases_explain_the_expected_boundary() -> None:
    development, holdout = _load_suites()
    reason_outcomes = {
        ExpectedOutcome.REJECTED,
        ExpectedOutcome.APPROVAL_REQUIRED,
        ExpectedOutcome.FAILED,
    }

    for case in (*development.cases, *holdout.cases):
        if case.expected_outcome in reason_outcomes:
            assert case.expected_reason_code


def test_resilience_cases_define_deterministic_faults_only() -> None:
    development, holdout = _load_suites()

    for case in (*development.cases, *holdout.cases):
        if case.category is EvaluationCategory.RESILIENCE:
            assert case.fault is not None
            assert case.fault.occurrences
            assert all(item >= 1 for item in case.fault.occurrences)
        else:
            assert case.fault is None
