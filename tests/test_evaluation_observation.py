from unittest.mock import Mock

import pytest

from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.evaluation_observation import (
    observe_analysis_state,
    read_evaluation_observation,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisResultStatus,
    ChartSpec,
    QueryRisk,
    RetrievalEvidence,
)
from retail_analytics_agent.workflow import create_initial_state


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id="EVAL-OBS-001",
        user_id="EVALUATOR-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )


def _completed_state():
    state = create_initial_state(_request())
    state.update(
        {
            "plan": AnalysisPlan(
                analysis_goal="按渠道统计销售额",
                metrics=["sales_amount"],
                dimensions=["channel"],
                time_range={"days": 30},
                limit=10,
            ),
            "retrieved_context": [
                RetrievalEvidence(
                    source_id="metric.sales_amount.v1",
                    content="paid sales use the deal price",
                ),
                RetrievalEvidence(
                    source_id="schema.join.orders.order_items",
                    content="orders.order_id = order_items.order_id",
                ),
            ],
            "generated_sql": (
                "SELECT o.channel, SUM(oi.quantity * oi.unit_price) "
                "FROM orders o JOIN order_items oi "
                "ON o.order_id = oi.order_id GROUP BY o.channel"
            ),
            "sql_valid": True,
            "query_risk": QueryRisk(
                requires_approval=False,
                result_limit=10,
            ),
            "query_rows": [
                {"channel": "京东", "sales_amount": "11300.00"}
            ],
            "chart_spec": ChartSpec(
                chart_type="bar",
                title="各渠道销售额",
                x_field="channel",
                y_fields=("sales_amount",),
            ),
            "final_answer": "京东渠道销售额为 11300.00 元。",
            "result_status": AnalysisResultStatus.SUCCEEDED,
            "trace": [
                "plan",
                "retrieve",
                "generate_sql",
                "validate_sql",
                "execute_sql",
                "summarize",
            ],
        }
    )
    return state


def test_observation_copies_internal_state_without_inventing_fields() -> None:
    observation = observe_analysis_state(_completed_state())

    assert observation.request_id == "EVAL-OBS-001"
    assert observation.evidence_source_ids == (
        "metric.sales_amount.v1",
        "schema.join.orders.order_items",
    )
    assert observation.generated_sql is not None
    assert observation.sql_safe is True
    assert observation.rows[0]["sales_amount"] == "11300.00"
    assert observation.chart_type.value == "bar"
    assert observation.database_called is True
    assert "evidence_match" not in type(observation).model_fields


def test_observation_preserves_failed_execution_as_raw_data() -> None:
    state = _completed_state()
    state.update(
        {
            "query_rows": [],
            "execution_error": "query timed out",
            "final_answer": "分析失败：query timed out",
            "result_status": None,
            "trace": [
                "plan",
                "retrieve",
                "generate_sql",
                "validate_sql",
                "execute_sql",
                "fail",
            ],
        }
    )

    observation = observe_analysis_state(state)

    assert observation.execution_error == "query timed out"
    assert observation.rows == ()
    assert observation.database_called is True
    assert observation.result_status is None


def test_observation_reads_the_existing_checkpoint_snapshot() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values=_completed_state())

    observation = read_evaluation_observation(graph, "EVAL-OBS-001")

    assert observation.request_id == "EVAL-OBS-001"
    graph.get_state.assert_called_once_with(
        {"configurable": {"thread_id": "EVAL-OBS-001"}}
    )


def test_observation_rejects_a_missing_snapshot() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values={})

    with pytest.raises(ValueError, match="snapshot was not found"):
        read_evaluation_observation(graph, "MISSING")


def test_public_response_still_omits_internal_sql() -> None:
    graph = Mock()
    graph.invoke.return_value = _completed_state()
    runner = LangGraphAnalysisRunner(graph)

    response = runner.run(
        _request(),
        AccessContext(
            user_id="EVALUATOR-001",
            role=AccessRole.ANALYST,
        ),
    )

    assert "generated_sql" not in response.model_dump()
    assert "sql_valid" not in response.model_dump()
