from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Protocol

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationCase,
    ExpectedOutcome,
)
from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.evaluation_observation import (
    AnalysisEvaluationObservation,
    read_evaluation_observation,
)
from retail_analytics_agent.evaluation_runs import (
    EvaluationRunRecord,
    EvaluationVariant,
)
from retail_analytics_agent.models import (
    AccessContext,
    AnalysisRequest,
    AnalysisResultStatus,
    ApprovalStatus,
)


class EvaluationCaseWorkflow(Protocol):
    """Run one case and return the trusted internal workflow observation."""

    def run_case(
        self,
        case: BusinessEvaluationCase,
        *,
        request_id: str,
    ) -> AnalysisEvaluationObservation: ...


@dataclass(frozen=True, slots=True)
class LangGraphEvaluationCaseWorkflow:
    """Run a real LangGraph request and read its trusted checkpoint state."""

    runner: LangGraphAnalysisRunner
    evaluator_user_id: str = "EVALUATION-USER"
    max_rows: int = 1000

    def run_case(
        self,
        case: BusinessEvaluationCase,
        *,
        request_id: str,
    ) -> AnalysisEvaluationObservation:
        request = AnalysisRequest(
            request_id=request_id,
            user_id=self.evaluator_user_id,
            question=case.question,
            max_rows=self.max_rows,
        )
        access_context = AccessContext(
            user_id=self.evaluator_user_id,
            role=case.access_role,
        )
        run_error: Exception | None = None
        try:
            self.runner.run(request, access_context)
        except Exception as exc:
            run_error = exc

        try:
            return read_evaluation_observation(self.runner.graph, request_id)
        except ValueError:
            if run_error is not None:
                raise run_error
            raise


ReasonCodeResolver = Callable[
    [AnalysisEvaluationObservation, Exception | None],
    str | None,
]
AnswerJudge = Callable[
    [BusinessEvaluationCase, AnalysisEvaluationObservation],
    bool | None,
]


def observation_outcome(
    observation: AnalysisEvaluationObservation,
) -> ExpectedOutcome:
    if observation.approval_status is ApprovalStatus.PENDING:
        return ExpectedOutcome.APPROVAL_REQUIRED
    if observation.approval_status is ApprovalStatus.REJECTED:
        return ExpectedOutcome.REJECTED
    if observation.execution_error is not None:
        return ExpectedOutcome.FAILED
    if (
        observation.sql_safe is False
        or observation.business_sql_valid is False
    ):
        return ExpectedOutcome.REJECTED
    if observation.result_status is AnalysisResultStatus.DEGRADED:
        return ExpectedOutcome.DEGRADED
    if observation.result_status is AnalysisResultStatus.SUCCEEDED:
        return ExpectedOutcome.SUCCEEDED
    return ExpectedOutcome.FAILED


def _default_reason_code(
    observation: AnalysisEvaluationObservation,
    error: Exception | None,
) -> str | None:
    if observation.approval_status is ApprovalStatus.PENDING:
        return (
            "sensitive_column"
            if observation.sensitive_columns
            else "high_result_limit"
        )
    message = (
        observation.business_sql_validation_error
        or observation.sql_validation_error
        or observation.execution_error
        or (str(error) if error is not None else None)
    )
    if not message:
        return None
    return message.split(":", maxsplit=1)[0].strip()


@dataclass(frozen=True, slots=True)
class ObservedWorkflowExecutor:
    """Evaluation executor that preserves raw workflow output without scoring."""

    variant: EvaluationVariant
    workflow: EvaluationCaseWorkflow
    execution_id: str
    reason_code_resolver: ReasonCodeResolver = _default_reason_code
    answer_judge: AnswerJudge | None = None

    def execute(
        self,
        case: BusinessEvaluationCase,
        *,
        variant: EvaluationVariant,
        run_index: int,
    ) -> EvaluationRunRecord:
        if variant is not self.variant:
            raise ValueError("executor variant does not match requested variant")
        request_id = (
            f"{self.execution_id}:{variant.value}:{case.case_id}:{run_index}"
        )
        started = perf_counter()
        error: Exception | None = None
        try:
            observation = self.workflow.run_case(case, request_id=request_id)
        except Exception as exc:
            error = exc
            latency_ms = max(0, round((perf_counter() - started) * 1000))
            return EvaluationRunRecord(
                case_id=case.case_id,
                variant=variant,
                run_index=run_index,
                actual_outcome=ExpectedOutcome.FAILED,
                actual_reason_code=type(exc).__name__,
                latency_ms=latency_ms,
                retry_count=0,
                error=str(exc),
            )

        latency_ms = max(0, round((perf_counter() - started) * 1000))
        answer_correct = (
            self.answer_judge(case, observation)
            if self.answer_judge is not None
            else None
        )
        return EvaluationRunRecord(
            case_id=case.case_id,
            variant=variant,
            run_index=run_index,
            actual_outcome=observation_outcome(observation),
            actual_plan=observation.plan,
            actual_source_ids=observation.evidence_source_ids,
            actual_sql=observation.generated_sql,
            sql_safe=observation.sql_safe,
            evidence_match=observation.business_sql_valid,
            actual_rows=observation.rows,
            actual_reason_code=self.reason_code_resolver(observation, error),
            actual_sensitive_columns=observation.sensitive_columns,
            actual_chart_type=observation.chart_type,
            answer_correct=answer_correct,
            database_called=observation.database_called,
            final_answer=observation.final_answer,
            latency_ms=latency_ms,
            retry_count=observation.retry_count,
            trace=observation.trace,
            error=(
                observation.execution_error
                or observation.business_sql_validation_error
                or observation.sql_validation_error
            ),
        )
