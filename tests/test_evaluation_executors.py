from pathlib import Path

import pytest

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationCase,
    ExpectedOutcome,
    load_business_evaluation_suite,
)
from retail_analytics_agent.evaluation_executors import (
    ObservedWorkflowExecutor,
    observation_outcome,
)
from retail_analytics_agent.evaluation_observation import (
    AnalysisEvaluationObservation,
)
from retail_analytics_agent.evaluation_runs import EvaluationVariant
from retail_analytics_agent.models import (
    AnalysisResultStatus,
    ApprovalStatus,
)


EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def _case() -> BusinessEvaluationCase:
    suite = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_development.json"
    )
    return next(case for case in suite.cases if case.expected_plan is not None)


def _observation(case: BusinessEvaluationCase) -> AnalysisEvaluationObservation:
    return AnalysisEvaluationObservation(
        request_id="internal-request",
        plan=case.expected_plan,
        evidence_source_ids=case.expected_source_ids,
        generated_sql=case.gold_sql,
        sql_safe=True,
        business_sql_valid=True,
        rows=case.expected_rows,
        chart_type=case.expected_chart_type,
        final_answer="trusted table result",
        result_status=AnalysisResultStatus.SUCCEEDED,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        retry_count=1,
        trace=("plan", "retrieve", "execute_sql", "summarize"),
        database_called=True,
    )


class _Workflow:
    def __init__(self, observation: AnalysisEvaluationObservation) -> None:
        self.observation = observation
        self.request_ids: list[str] = []

    def run_case(
        self,
        case: BusinessEvaluationCase,
        *,
        request_id: str,
    ) -> AnalysisEvaluationObservation:
        self.request_ids.append(request_id)
        return self.observation


def test_executor_converts_observation_to_raw_run_without_scoring() -> None:
    case = _case()
    workflow = _Workflow(_observation(case))
    executor = ObservedWorkflowExecutor(
        variant=EvaluationVariant.RETRIEVAL,
        workflow=workflow,
        execution_id="EXP-001",
    )

    run = executor.execute(
        case,
        variant=EvaluationVariant.RETRIEVAL,
        run_index=2,
    )

    assert run.actual_outcome is ExpectedOutcome.SUCCEEDED
    assert run.actual_source_ids == case.expected_source_ids
    assert run.evidence_match is True
    assert run.database_called is True
    assert run.answer_correct is None
    assert workflow.request_ids == [
        f"EXP-001:retrieval:{case.case_id}:2"
    ]


def test_pending_observation_maps_to_approval_required() -> None:
    observation = _observation(_case()).model_copy(
        update={
            "approval_status": ApprovalStatus.PENDING,
            "sensitive_columns": ("refunds.reason",),
            "database_called": False,
            "rows": (),
            "result_status": None,
        }
    )

    assert observation_outcome(observation) is ExpectedOutcome.APPROVAL_REQUIRED


def test_executor_rejects_variant_mismatch() -> None:
    case = _case()
    executor = ObservedWorkflowExecutor(
        variant=EvaluationVariant.BASELINE,
        workflow=_Workflow(_observation(case)),
        execution_id="EXP-001",
    )

    with pytest.raises(ValueError, match="variant does not match"):
        executor.execute(
            case,
            variant=EvaluationVariant.RERANKER,
            run_index=1,
        )


def test_executor_preserves_workflow_exception_as_failed_raw_run() -> None:
    class FailingWorkflow:
        def run_case(self, case, *, request_id):
            raise TimeoutError("model timed out")

    run = ObservedWorkflowExecutor(
        variant=EvaluationVariant.BASELINE,
        workflow=FailingWorkflow(),
        execution_id="EXP-001",
    ).execute(
        _case(),
        variant=EvaluationVariant.BASELINE,
        run_index=1,
    )

    assert run.actual_outcome is ExpectedOutcome.FAILED
    assert run.actual_reason_code == "TimeoutError"
    assert run.error == "model timed out"
