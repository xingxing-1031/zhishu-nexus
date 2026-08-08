from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.models import (
    AnalysisPlan,
    AnalysisResultStatus,
    ApprovalStatus,
    ChartType,
)
from retail_analytics_agent.workflow import (
    EXECUTE_SQL_NODE,
    AnalysisState,
    CompiledAnalysisGraph,
    create_thread_config,
)


class AnalysisEvaluationObservation(BaseModel):
    """Internal, immutable snapshot used by the evaluation adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    scope_supported: bool | None = None
    scope_rejection_reason: str | None = None
    plan: AnalysisPlan | None = None
    evidence_source_ids: tuple[str, ...] = ()
    generated_sql: str | None = None
    sql_safe: bool | None = None
    business_sql_valid: bool | None = None
    rows: tuple[dict[str, Any], ...] = ()
    chart_type: ChartType | None = None
    final_answer: str | None = None
    result_status: AnalysisResultStatus | None = None
    approval_status: ApprovalStatus
    sensitive_columns: tuple[str, ...] = ()
    sql_validation_error: str | None = None
    business_sql_validation_error: str | None = None
    execution_error: str | None = None
    degradation_reason: str | None = None
    workflow_error: str | None = None
    retry_count: int = Field(ge=0)
    trace: tuple[str, ...] = ()
    database_called: bool = False


def observe_analysis_state(
    state: AnalysisState,
) -> AnalysisEvaluationObservation:
    """Copy raw evaluation fields without changing or completing the state."""

    chart = state["chart_spec"]
    risk = state["query_risk"]
    trace = tuple(state["trace"])
    return AnalysisEvaluationObservation(
        request_id=state["request_id"],
        scope_supported=state.get("scope_supported"),
        scope_rejection_reason=state.get("scope_rejection_reason"),
        plan=state["plan"],
        evidence_source_ids=tuple(
            item.source_id for item in state["retrieved_context"]
        ),
        generated_sql=state["generated_sql"],
        sql_safe=state["sql_valid"],
        business_sql_valid=state["business_sql_valid"],
        rows=tuple(state["query_rows"]),
        chart_type=chart.chart_type if chart is not None else None,
        final_answer=state["final_answer"],
        result_status=state["result_status"],
        approval_status=state["approval_status"],
        sensitive_columns=(
            risk.sensitive_columns if risk is not None else ()
        ),
        sql_validation_error=state["sql_validation_error"],
        business_sql_validation_error=(
            state["business_sql_validation_error"]
        ),
        execution_error=state["execution_error"],
        degradation_reason=state["degradation_reason"],
        retry_count=state["retry_count"],
        trace=trace,
        database_called=EXECUTE_SQL_NODE in trace,
    )


def read_evaluation_observation(
    graph: CompiledAnalysisGraph,
    request_id: str,
) -> AnalysisEvaluationObservation:
    """Read one trusted LangGraph snapshot for an internal evaluator."""

    snapshot = graph.get_state(create_thread_config(request_id))
    if not snapshot.values:
        raise ValueError("analysis evaluation snapshot was not found")
    return observe_analysis_state(snapshot.values)
