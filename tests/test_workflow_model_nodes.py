from unittest.mock import Mock

import pytest

from retail_analytics_agent.models import (
    AnalysisPlan,
    AnalysisRequest,
    RetrievalEvidence,
)
from retail_analytics_agent.workflow import (
    build_analysis_graph,
    create_fail_node,
    create_initial_state,
    create_plan_node,
    create_sql_generation_node,
    create_summarize_node,
    create_workflow_nodes,
)


def _state():
    return create_initial_state(
        AnalysisRequest(
            request_id="REQ-MODEL-001",
            user_id="USER-001",
            question="最近30天各渠道销售额是多少？",
            max_rows=10,
        )
    )


def _plan(limit: int = 10) -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计最近 30 天各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        time_range={"days": 30},
        limit=limit,
    )


def test_plan_node_writes_validated_plan_to_state() -> None:
    model = Mock()
    model.plan.return_value = _plan()

    update = create_plan_node(model)(_state())

    assert update == {"plan": _plan(), "trace": ["plan"]}
    model.plan.assert_called_once_with(
        "最近30天各渠道销售额是多少？",
        max_rows=10,
    )


def test_plan_node_rejects_model_limit_above_request_boundary() -> None:
    model = Mock()
    model.plan.return_value = _plan(limit=11)

    with pytest.raises(ValueError, match="must not exceed max_rows"):
        create_plan_node(model)(_state())


def test_sql_generation_node_requires_both_plan_and_evidence() -> None:
    model = Mock()
    state = _state()

    with pytest.raises(ValueError, match="analysis plan is required"):
        create_sql_generation_node(model)(state)

    state["plan"] = _plan()
    with pytest.raises(ValueError, match="retrieval evidence is required"):
        create_sql_generation_node(model)(state)


def test_sql_generation_node_passes_validation_error_on_retry() -> None:
    model = Mock()
    model.generate.return_value = "SELECT channel FROM orders"
    state = _state()
    state["plan"] = _plan()
    state["retrieved_context"] = [
        RetrievalEvidence(
            source_id="schema.orders",
            content="Table orders",
        )
    ]
    state["sql_validation_error"] = "unsafe SQL"
    state["sql_valid"] = False

    update = create_sql_generation_node(model)(state)

    assert update["generated_sql"] == "SELECT channel FROM orders"
    assert update["prepared_sql"] is None
    assert update["sql_valid"] is None
    model.generate.assert_called_once_with(
        question=state["question"],
        plan=state["plan"],
        evidence=state["retrieved_context"],
        validation_error="unsafe SQL",
    )


def test_summarize_node_passes_zero_rows_as_successful_result() -> None:
    model = Mock()
    model.summarize.return_value = "没有符合条件的数据。"
    state = _state()
    state["plan"] = _plan()
    state["query_rows"] = []

    update = create_summarize_node(model)(state)

    assert update == {
        "final_answer": "没有符合条件的数据。",
        "chart_spec": None,
        "trace": ["summarize"],
    }
    model.summarize.assert_called_once_with(
        question=state["question"],
        plan=state["plan"],
        rows=[],
    )


def test_fail_node_uses_execution_error_before_validation_error() -> None:
    state = _state()
    state["execution_error"] = "query timed out"
    state["sql_validation_error"] = "unsafe SQL"

    assert create_fail_node()(state) == {
        "final_answer": "分析失败：query timed out",
        "trace": ["fail"],
    }


def test_workflow_node_factory_wires_complete_success_path() -> None:
    planner = Mock()
    planner.plan.return_value = _plan()
    retrieval_tool = Mock()
    retrieval_tool.retrieve.return_value = [
        RetrievalEvidence(
            source_id="schema.orders",
            content="Table orders",
        )
    ]
    sql_generator = Mock()
    sql_generator.generate.return_value = "SELECT channel FROM orders"
    validation_tool = Mock()
    validation_tool.validate.return_value = Mock()
    execution_tool = Mock()
    execution_tool.execute.return_value = Mock(
        rows=[{"channel": "jd", "sales_amount": "9000.00"}]
    )
    summarizer = Mock()
    summarizer.summarize.return_value = "京东渠道销售额为 9000.00 元。"
    nodes = create_workflow_nodes(
        planner=planner,
        retrieval_tool=retrieval_tool,
        sql_generator=sql_generator,
        validation_tool=validation_tool,
        execution_tool=execution_tool,
        summarizer=summarizer,
    )

    result = build_analysis_graph(nodes).invoke(_state())

    assert result["final_answer"] == "京东渠道销售额为 9000.00 元。"
    assert result["chart_spec"].model_dump(mode="json") == {
        "chart_type": "bar",
        "title": "统计最近 30 天各渠道销售额",
        "x_field": "channel",
        "y_fields": ["sales_amount"],
    }
    assert result["trace"] == [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "summarize",
    ]
