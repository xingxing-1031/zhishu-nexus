from unittest.mock import Mock

from retail_analytics_agent.models import (
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
)
from retail_analytics_agent.sql_safety import prepare_safe_sql
from retail_analytics_agent.workflow import (
    build_analysis_graph,
    create_initial_state,
    create_sql_business_validation_node,
    create_workflow_nodes,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    SQLConsistencyValidationTool,
)


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-BUSINESS-SQL-001",
        user_id="USER-001",
        question="按渠道统计销售额",
        max_rows=10,
    )


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="按渠道统计销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        limit=10,
    )


def _valid_sql() -> str:
    return (
        "SELECT o.channel, SUM(oi.quantity * oi.unit_price) AS sales_amount "
        "FROM orders AS o JOIN order_items AS oi "
        "ON oi.order_id = o.order_id "
        "WHERE o.status = 'paid' "
        "AND o.created_at >= %(start_time)s "
        "AND o.created_at < %(end_time)s "
        "GROUP BY o.channel"
    )


def _state(sql: str):
    state = create_initial_state(_request())
    plan = _plan()
    state.update(
        {
            "plan": plan,
            "retrieved_context": CatalogRetrievalTool().retrieve(plan),
            "generated_sql": sql,
            "sql_valid": True,
        }
    )
    return state


def test_business_validation_node_records_independent_success() -> None:
    update = create_sql_business_validation_node(
        SQLConsistencyValidationTool()
    )(_state(_valid_sql()))

    assert update == {
        "business_sql_valid": True,
        "business_sql_validation_error": None,
        "trace": ["validate_business_sql"],
    }


def test_business_validation_node_records_reason_and_retry() -> None:
    invalid_sql = _valid_sql().replace(
        "WHERE o.status = 'paid' AND ",
        "WHERE ",
    )

    update = create_sql_business_validation_node(
        SQLConsistencyValidationTool()
    )(_state(invalid_sql))

    assert update["business_sql_valid"] is False
    assert "missing_required_filter:orders.status" in update[
        "business_sql_validation_error"
    ]
    assert update["retry_count"] == 1
    assert update["trace"] == ["validate_business_sql"]


def test_business_invalid_sql_never_reaches_database() -> None:
    planner = Mock()
    planner.plan.return_value = _plan()
    retrieval_tool = CatalogRetrievalTool()
    sql_generator = Mock()
    sql_generator.generate.return_value = _valid_sql().replace(
        "WHERE o.status = 'paid' AND ",
        "WHERE ",
    )
    safety_tool = Mock()
    safety_tool.validate.return_value = prepare_safe_sql(
        sql_generator.generate.return_value,
        max_rows=10,
        access_role=AccessRole.ANALYST,
    )
    execution_tool = Mock()
    summarizer = Mock()
    nodes = create_workflow_nodes(
        planner=planner,
        retrieval_tool=retrieval_tool,
        sql_generator=sql_generator,
        validation_tool=safety_tool,
        business_validation_tool=SQLConsistencyValidationTool(),
        approval_audit_sink=Mock(),
        execution_tool=execution_tool,
        summarizer=summarizer,
    )

    result = build_analysis_graph(nodes).invoke(
        create_initial_state(_request(), max_retries=0)
    )

    assert result["sql_valid"] is True
    assert result["business_sql_valid"] is False
    assert result["retry_count"] == 1
    assert result["trace"] == [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
        "validate_business_sql",
        "fail",
    ]
    execution_tool.execute.assert_not_called()
    summarizer.summarize.assert_not_called()


def test_business_valid_sql_reaches_database_after_both_checks() -> None:
    planner = Mock()
    planner.plan.return_value = _plan()
    sql_generator = Mock()
    sql_generator.generate.return_value = _valid_sql()
    safety_tool = Mock()
    safety_tool.validate.return_value = prepare_safe_sql(
        _valid_sql(),
        max_rows=10,
    )
    execution_tool = Mock()
    execution_tool.execute.return_value = Mock(
        rows=[{"channel": "京东", "sales_amount": "11300.00"}]
    )
    summarizer = Mock()
    summarizer.summarize.return_value = "京东渠道销售额为 11300.00 元。"
    nodes = create_workflow_nodes(
        planner=planner,
        retrieval_tool=CatalogRetrievalTool(),
        sql_generator=sql_generator,
        validation_tool=safety_tool,
        business_validation_tool=SQLConsistencyValidationTool(),
        approval_audit_sink=Mock(),
        execution_tool=execution_tool,
        summarizer=summarizer,
    )

    result = build_analysis_graph(nodes).invoke(create_initial_state(_request()))

    assert result["sql_valid"] is True
    assert result["business_sql_valid"] is True
    assert result["trace"] == [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
        "validate_business_sql",
        "assess_risk",
        "execute_sql",
        "summarize",
    ]
    execution_tool.execute.assert_called_once()
