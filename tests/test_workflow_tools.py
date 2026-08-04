from unittest.mock import Mock, call

import pytest

from retail_analytics_agent.audit import QueryAuditRecord, QueryAuditStatus
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    RetrievalEvidence,
)
from retail_analytics_agent.query_service import (
    SET_STATEMENT_TIMEOUT_SQL,
    SET_TRANSACTION_READ_ONLY_SQL,
    SafeQueryResult,
)
from retail_analytics_agent.sql_safety import PreparedSQL
from retail_analytics_agent.workflow import (
    create_initial_state,
    create_retrieve_node,
    create_sql_execution_node,
    create_sql_validation_node,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    CatalogRetrievalToolError,
    SQLExecutionToolError,
    SQLGlotValidationTool,
    SQLValidationToolError,
    SafeSQLExecutionTool,
)


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-TOOL-001",
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=50,
    )


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        filters=[
            {
                "field": "order_status",
                "operator": "equals",
                "value": "paid",
            }
        ],
        time_range={"days": 30},
        limit=50,
    )


def _prepared_sql() -> PreparedSQL:
    return PreparedSQL(
        sql="SELECT channel FROM orders LIMIT 50",
        tables=("orders",),
        max_rows=50,
        access_role=AccessRole.ANALYST,
    )


def test_retrieve_node_writes_structured_evidence_to_state() -> None:
    tool = Mock()
    evidence = [
        RetrievalEvidence(
            source_id="metric.sales_amount",
            content="sales_amount uses paid orders.amount",
        )
    ]
    tool.retrieve.return_value = evidence
    state = create_initial_state(_request())
    state["plan"] = _plan()

    update = create_retrieve_node(tool)(state)

    assert update["retrieved_context"] == evidence
    assert update["trace"] == ["retrieve"]
    tool.retrieve.assert_called_once_with(state["plan"])


def test_retrieve_node_requires_a_validated_plan() -> None:
    state = create_initial_state(_request())

    with pytest.raises(
        ValueError,
        match="analysis plan is required before retrieval",
    ):
        create_retrieve_node(Mock())(state)


def test_catalog_retrieval_returns_product_sales_evidence() -> None:
    plan = AnalysisPlan(
        analysis_goal="按商品统计销售额",
        metrics=["sales_amount"],
        dimensions=["product"],
    )

    evidence = CatalogRetrievalTool().retrieve(plan)

    assert [item.source_id for item in evidence] == [
        "metric.sales_amount.v1",
        "schema.orders",
        "schema.products",
        "schema.order_items",
        "schema.join.orders.order_items",
        "schema.join.products.order_items",
    ]


def test_catalog_retrieval_returns_only_refund_status_evidence() -> None:
    plan = AnalysisPlan(
        analysis_goal="按退款状态统计退款金额",
        metrics=["refund_amount"],
        dimensions=["refund_status"],
    )

    evidence = CatalogRetrievalTool().retrieve(plan)

    assert [item.source_id for item in evidence] == [
        "metric.refund_amount.v1",
        "schema.refunds",
    ]


def test_catalog_retrieval_deduplicates_shared_schema_evidence() -> None:
    plan = AnalysisPlan(
        analysis_goal="按渠道统计销售额和销量",
        metrics=["sales_amount", "units_sold"],
        dimensions=["channel"],
    )

    evidence = CatalogRetrievalTool().retrieve(plan)
    source_ids = [item.source_id for item in evidence]

    assert source_ids == [
        "metric.sales_amount.v1",
        "metric.units_sold.v1",
        "schema.orders",
        "schema.order_items",
        "schema.join.orders.order_items",
    ]
    assert len(source_ids) == len(set(source_ids))


def test_catalog_retrieval_uses_filter_tables_and_approved_join_path() -> None:
    plan = AnalysisPlan(
        analysis_goal="统计指定商品的订单数",
        metrics=["order_count"],
        filters=[
            {
                "field": "product_id",
                "operator": "equals",
                "value": "P001",
            }
        ],
    )

    evidence = CatalogRetrievalTool().retrieve(plan)

    assert [item.source_id for item in evidence] == [
        "metric.order_count.v1",
        "schema.orders",
        "schema.products",
        "schema.order_items",
        "schema.join.orders.order_items",
        "schema.join.products.order_items",
    ]


def test_catalog_retrieval_rejects_unsupported_metric_dimension() -> None:
    plan = AnalysisPlan(
        analysis_goal="按商品统计退款金额",
        metrics=["refund_amount"],
        dimensions=["product"],
    )

    with pytest.raises(
        CatalogRetrievalToolError,
        match="refund_amount does not support dimensions: product",
    ):
        CatalogRetrievalTool().retrieve(plan)


def test_real_catalog_retrieval_node_writes_evidence_to_state() -> None:
    state = create_initial_state(_request())
    state["plan"] = _plan()

    update = create_retrieve_node(CatalogRetrievalTool())(state)

    assert [
        item.source_id for item in update["retrieved_context"]
    ] == [
        "metric.sales_amount.v1",
        "schema.orders",
        "schema.order_items",
        "schema.join.orders.order_items",
    ]
    assert update["trace"] == ["retrieve"]


def test_validation_node_stores_prepared_sql() -> None:
    tool = Mock()
    prepared = _prepared_sql()
    tool.validate.return_value = prepared
    state = create_initial_state(_request())
    state["generated_sql"] = "SELECT channel FROM orders"

    update = create_sql_validation_node(tool)(state)

    assert update["prepared_sql"] == prepared
    assert update["sql_valid"] is True
    assert update["sql_validation_error"] is None
    tool.validate.assert_called_once_with(
        request_id="REQ-TOOL-001",
        user_id="USER-001",
        sql="SELECT channel FROM orders",
        max_rows=50,
        access_role=AccessRole.ANALYST,
    )


def test_validation_node_converts_rejection_into_retry_state() -> None:
    tool = Mock()
    tool.validate.side_effect = SQLValidationToolError("unsafe SQL")
    state = create_initial_state(_request())
    state["generated_sql"] = "DELETE FROM orders"

    update = create_sql_validation_node(tool)(state)

    assert update["prepared_sql"] is None
    assert update["sql_valid"] is False
    assert update["sql_validation_error"] == "unsafe SQL"
    assert update["retry_count"] == 1


def test_execution_node_writes_rows_to_state() -> None:
    tool = Mock()
    rows = [{"channel": "jd", "sales_amount": "100.00"}]
    tool.execute.return_value = SafeQueryResult(
        rows=rows,
        audit=QueryAuditRecord(
            request_id="REQ-TOOL-001",
            user_id="USER-001",
            original_sql="SELECT channel FROM orders",
            executed_sql="SELECT channel FROM orders LIMIT 50",
            status=QueryAuditStatus.SUCCEEDED,
            row_count=1,
            duration_ms=1,
        ),
    )
    state = create_initial_state(_request())
    state["generated_sql"] = "SELECT channel FROM orders"
    state["prepared_sql"] = _prepared_sql()

    update = create_sql_execution_node(tool)(state)

    assert update["query_rows"] == rows
    assert update["execution_error"] is None
    tool.execute.assert_called_once_with(
        request_id="REQ-TOOL-001",
        user_id="USER-001",
        original_sql="SELECT channel FROM orders",
        prepared_sql=state["prepared_sql"],
    )


def test_execution_node_converts_tool_error_into_failure_state() -> None:
    tool = Mock()
    tool.execute.side_effect = SQLExecutionToolError("query timed out")
    state = create_initial_state(_request())
    state["generated_sql"] = "SELECT channel FROM orders"
    state["prepared_sql"] = _prepared_sql()

    update = create_sql_execution_node(tool)(state)

    assert update["query_rows"] == []
    assert update["execution_error"] == "query timed out"


def test_validation_adapter_uses_sql_safety_and_audits_rejection() -> None:
    audit_sink = Mock()
    tool = SQLGlotValidationTool(audit_sink=audit_sink)

    prepared = tool.validate(
        request_id="REQ-TOOL-001",
        user_id="USER-001",
        sql="SELECT order_id FROM orders",
        max_rows=25,
        access_role=AccessRole.ANALYST,
    )

    assert prepared.sql == "SELECT order_id FROM orders LIMIT 25"
    audit_sink.record.assert_not_called()

    with pytest.raises(
        SQLValidationToolError,
        match="wildcard columns are not allowed",
    ):
        tool.validate(
            request_id="REQ-TOOL-002",
            user_id="USER-001",
            sql="SELECT * FROM orders",
            max_rows=25,
            access_role=AccessRole.ANALYST,
        )

    audit = audit_sink.record.call_args.args[0]
    assert audit.request_id == "REQ-TOOL-002"
    assert audit.status is QueryAuditStatus.REJECTED


def test_execution_adapter_uses_prepared_sql_and_audits_success() -> None:
    connection = Mock()
    result_cursor = Mock()
    result_cursor.fetchall.return_value = [{"channel": "jd"}]
    connection.execute.side_effect = [Mock(), Mock(), result_cursor]
    audit_sink = Mock()
    tool = SafeSQLExecutionTool(
        connection=connection,
        audit_sink=audit_sink,
        statement_timeout_ms=1500,
    )

    result = tool.execute(
        request_id="REQ-TOOL-001",
        user_id="USER-001",
        original_sql="SELECT channel FROM orders",
        prepared_sql=_prepared_sql(),
    )

    assert result.rows == [{"channel": "jd"}]
    assert connection.execute.call_args_list == [
        call(SET_TRANSACTION_READ_ONLY_SQL),
        call(
            SET_STATEMENT_TIMEOUT_SQL,
            {"statement_timeout": "1500ms"},
        ),
        call("SELECT channel FROM orders LIMIT 50"),
    ]
    assert result.audit.original_sql == "SELECT channel FROM orders"
    assert result.audit.status is QueryAuditStatus.SUCCEEDED
