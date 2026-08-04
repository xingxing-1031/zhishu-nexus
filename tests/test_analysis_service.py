from unittest.mock import Mock

import pytest

from retail_analytics_agent.analysis_service import (
    AnalysisRunError,
    LangGraphAnalysisRunner,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    ChartSpec,
)
from retail_analytics_agent.workflow import create_initial_state


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-SERVICE-001",
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )


def _access_context() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _successful_state():
    state = create_initial_state(_request())
    state.update(
        {
            "plan": AnalysisPlan(
                analysis_goal="各渠道销售额",
                metrics=["sales_amount"],
                dimensions=["channel"],
            ),
            "sql_valid": True,
            "query_rows": [
                {"channel": "京东", "sales_amount": "11300.00"}
            ],
            "final_answer": "京东渠道销售额为 11300.00 元。",
            "chart_spec": ChartSpec(
                chart_type="bar",
                title="各渠道销售额",
                x_field="channel",
                y_fields=("sales_amount",),
            ),
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


def test_runner_converts_successful_state_to_public_response() -> None:
    graph = Mock()
    graph.invoke.return_value = _successful_state()
    runner = LangGraphAnalysisRunner(graph)

    response = runner.run(_request(), _access_context())

    assert response.request_id == "REQ-SERVICE-001"
    assert response.access_role is AccessRole.ANALYST
    assert response.answer == "京东渠道销售额为 11300.00 元。"
    assert response.chart_spec is not None
    assert response.chart_spec.x_field == "channel"
    assert response.trace[-1] == "summarize"
    graph.invoke.assert_called_once()


def test_runner_rejects_failed_execution_state() -> None:
    graph = Mock()
    state = _successful_state()
    state["execution_error"] = "query timed out"
    graph.invoke.return_value = state

    with pytest.raises(AnalysisRunError, match="query timed out"):
        LangGraphAnalysisRunner(graph).run(_request(), _access_context())


def test_runner_streams_node_statuses_then_public_result() -> None:
    graph = Mock()
    planned = create_initial_state(_request())
    planned["trace"] = ["plan"]
    retrieved = create_initial_state(_request())
    retrieved["trace"] = ["plan", "retrieve"]
    successful = _successful_state()
    graph.stream.return_value = [planned, retrieved, successful]

    events = list(
        LangGraphAnalysisRunner(graph).stream(_request(), _access_context())
    )

    assert [(event.event.value, event.node) for event in events] == [
        ("status", None),
        ("status", "plan"),
        ("status", "retrieve"),
        ("status", "summarize"),
        ("result", None),
    ]
    assert events[-1].response is not None
    assert events[-1].response.request_id == "REQ-SERVICE-001"
    graph.stream.assert_called_once()
