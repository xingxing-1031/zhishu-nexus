from pathlib import Path
from unittest.mock import Mock

import pytest

from retail_analytics_agent.business_evaluation import (
    load_business_evaluation_suite,
)
from retail_analytics_agent.evaluation_runs import (
    EvaluationRunRecord,
    EvaluationVariant,
)
from retail_analytics_agent.final_acceptance import run_final_acceptance
from retail_analytics_agent.business_evaluation import ExpectedOutcome


EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def _single_rejection_suite():
    suite = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_holdout.json"
    )
    case = next(
        item
        for item in suite.cases
        if item.case_id == "holdout-unsupported-conversion"
    )
    return suite.model_copy(update={"cases": (case,)})


def test_final_acceptance_runs_frozen_case_once() -> None:
    suite = _single_rejection_suite()
    executor = Mock()
    executor.variant = EvaluationVariant.BASELINE
    executor.execute.return_value = EvaluationRunRecord(
        case_id=suite.cases[0].case_id,
        variant=EvaluationVariant.BASELINE,
        run_index=1,
        actual_outcome=ExpectedOutcome.REJECTED,
        scope_rejection_reason="unsupported_metric",
        actual_reason_code="unsupported_metric",
        latency_ms=12,
        retry_count=0,
    )

    report = run_final_acceptance(
        execution_id="acceptance-test",
        model_id="qwen3:4b",
        model_provider="ollama",
        suite=suite,
        executor=executor,
    )

    assert report.summary.run_count == 1
    assert report.summary.core_pass_rate == 1
    executor.execute.assert_called_once_with(
        suite.cases[0],
        variant=EvaluationVariant.BASELINE,
        run_index=1,
    )


def test_final_acceptance_rejects_development_suite() -> None:
    suite = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_development.json"
    )
    executor = Mock(variant=EvaluationVariant.BASELINE)

    with pytest.raises(ValueError, match="frozen holdout"):
        run_final_acceptance(
            execution_id="acceptance-test",
            model_id="qwen3:4b",
            model_provider="ollama",
            suite=suite,
            executor=executor,
        )


def test_final_acceptance_requires_deployed_baseline_retrieval() -> None:
    suite = _single_rejection_suite()
    executor = Mock(variant=EvaluationVariant.RERANKER)

    with pytest.raises(ValueError, match="deployed baseline retrieval"):
        run_final_acceptance(
            execution_id="acceptance-test",
            model_id="qwen3:4b",
            model_provider="ollama",
            suite=suite,
            executor=executor,
        )
