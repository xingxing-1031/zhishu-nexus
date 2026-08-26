from __future__ import annotations

import pytest

from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.evaluation_layers import (
    aggregate_layer_metrics,
    build_layer_metrics_report,
)
from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    ApprovalStatus,
    QueryRisk,
    RetrievalEvidence,
)
from retail_analytics_agent.tracing import (
    ExecutionTraceEvent,
    InMemoryExecutionTraceStore,
    TraceErrorCategory,
    TraceStatus,
)
from retail_analytics_agent.workflow import WorkflowNodes, build_analysis_graph
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalToolError,
    SQLBusinessConsistencyToolError,
    SQLExecutionToolError,
    SQLValidationToolError,
)

_REQUEST_ID = "REQ-LAYERS-001"


def _event(
    layer: TraceErrorCategory,
    status: TraceStatus,
    *,
    component: str = "node.x",
) -> ExecutionTraceEvent:
    return ExecutionTraceEvent(
        request_id=_REQUEST_ID,
        component=component,
        status=status,
        error_category=layer,
    )


# --- 与 test_fault_matrix._base_nodes 同构：跨阶段闭环依赖相同的节点 mocks ---


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id=_REQUEST_ID,
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )


def _analyst() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        limit=10,
    )


def _base_nodes() -> WorkflowNodes:
    def plan(state: dict) -> dict:
        return {"plan": _plan(), "trace": ["plan"]}

    def retrieve(state: dict) -> dict:
        return {
            "retrieved_context": [
                RetrievalEvidence(source_id="schema.orders", content="orders.channel")
            ],
            "trace": ["retrieve"],
        }

    def generate_sql(state: dict) -> dict:
        return {
            "generated_sql": "SELECT channel FROM orders",
            "trace": ["generate_sql"],
        }

    def validate_sql(state: dict) -> dict:
        return {
            "sql_valid": True,
            "sql_validation_error": None,
            "trace": ["validate_sql"],
        }

    def validate_business_sql(state: dict) -> dict:
        return {
            "business_sql_valid": True,
            "business_sql_validation_error": None,
            "trace": ["validate_business_sql"],
        }

    def assess_risk(state: dict) -> dict:
        return {
            "query_risk": QueryRisk(requires_approval=False, result_limit=10),
            "approval_status": ApprovalStatus.NOT_REQUIRED,
            "trace": ["assess_risk"],
        }

    def request_approval(state: dict) -> dict:
        raise AssertionError("low-risk query must not request approval")

    def execute_sql(state: dict) -> dict:
        return {
            "query_rows": [{"channel": "京东", "sales_amount": "11300.00"}],
            "execution_error": None,
            "trace": ["execute_sql"],
        }

    def summarize(state: dict) -> dict:
        return {
            "final_answer": f"返回 {len(state['query_rows'])} 行结果",
            "trace": ["summarize"],
        }

    def fail(state: dict) -> dict:
        reason = (
            state["execution_error"]
            or state["approval_reason"]
            or state["scope_rejection_reason"]
            or state["sql_validation_error"]
        )
        return {"final_answer": f"分析失败：{reason}", "trace": ["fail"]}

    return WorkflowNodes(
        plan=plan,
        retrieve=retrieve,
        generate_sql=generate_sql,
        validate_sql=validate_sql,
        assess_risk=assess_risk,
        request_approval=request_approval,
        execute_sql=execute_sql,
        summarize=summarize,
        fail=fail,
        validate_business_sql=validate_business_sql,
    )


_NODE_FAULTS = [
    (
        "tool_timeout",
        "execute_sql",
        SQLExecutionToolError("tool_timeout"),
        TraceErrorCategory.TOOL,
    ),
    (
        "tool_unauthorized",
        "execute_sql",
        SQLExecutionToolError("tool_unauthorized"),
        TraceErrorCategory.TOOL,
    ),
    (
        "database_unavailable",
        "execute_sql",
        SQLExecutionToolError("database unavailable"),
        TraceErrorCategory.TOOL,
    ),
    (
        "rag_empty_evidence",
        "retrieve",
        CatalogRetrievalToolError("no evidence found"),
        TraceErrorCategory.TOOL,
    ),
    (
        "sql_ast_rejected",
        "validate_sql",
        SQLValidationToolError("SQL AST rejected"),
        TraceErrorCategory.TOOL,
    ),
    (
        "business_check_failed",
        "validate_business_sql",
        SQLBusinessConsistencyToolError("business check failed"),
        TraceErrorCategory.TOOL,
    ),
]


def test_aggregate_layer_metrics_counts_failures_per_layer() -> None:
    events = tuple(
        _event(layer, TraceStatus.FAILED) for layer in TraceErrorCategory
    ) + tuple(
        _event(TraceErrorCategory.MODEL, TraceStatus.SUCCEEDED) for _ in range(3)
    )

    metrics = {m.layer: m for m in aggregate_layer_metrics(events)}

    assert set(metrics) == set(TraceErrorCategory)
    for layer in TraceErrorCategory:
        assert metrics[layer].failure_count == 1
    assert metrics[TraceErrorCategory.MODEL].event_count == 4
    assert metrics[TraceErrorCategory.MODEL].success_rate == pytest.approx(0.75)


def test_aggregate_skips_events_without_category() -> None:
    events = (
        ExecutionTraceEvent(
            request_id=_REQUEST_ID,
            component="node.plan",
            status=TraceStatus.STARTED,
        ),
        ExecutionTraceEvent(
            request_id=_REQUEST_ID,
            component="node.plan",
            status=TraceStatus.SUCCEEDED,
        ),
        _event(
            TraceErrorCategory.TOOL,
            TraceStatus.FAILED,
            component="node.execute_sql",
        ),
    )

    metrics = aggregate_layer_metrics(events)

    assert len(metrics) == 1
    assert metrics[0].layer is TraceErrorCategory.TOOL
    assert metrics[0].event_count == 1
    assert metrics[0].failure_count == 1
    assert metrics[0].success_rate == 0.0


def test_layer_report_has_version_and_totals() -> None:
    events = (
        _event(TraceErrorCategory.TOOL, TraceStatus.FAILED),
        _event(TraceErrorCategory.MODEL, TraceStatus.SUCCEEDED),
        ExecutionTraceEvent(
            request_id=_REQUEST_ID,
            component="node.plan",
            status=TraceStatus.SUCCEEDED,
        ),
    )

    report = build_layer_metrics_report(_REQUEST_ID, events)

    assert report.request_id == _REQUEST_ID
    assert report.version == 1
    assert report.event_count == len(events) == 3
    assert len(report.layers) == len(tuple(TraceErrorCategory))
    assert {m.layer for m in report.layers} == set(TraceErrorCategory)
    assert report.layers[0].layer is TraceErrorCategory.MODEL
    empty = next(m for m in report.layers if m.event_count == 0)
    assert empty.success_rate == 0.0
    tool = next(m for m in report.layers if m.layer is TraceErrorCategory.TOOL)
    assert tool.failure_count == 1
    assert tool.success_rate == 0.0


def test_fault_matrix_trace_feeds_layer_report() -> None:
    """跨阶段闭环：阶段 7 节点级故障注入产生的 trace 归因到 tool 层。"""
    events = []
    for _name, node_name, error, _category in _NODE_FAULTS:
        graph = build_analysis_graph(_base_nodes())
        store = InMemoryExecutionTraceStore()
        runner = LangGraphAnalysisRunner(
            graph,
            fault_injector=ScriptedFaultInjector(
                (FaultRule(f"node.{node_name}", 1, error),)
            ),
            trace_store=store,
        )
        with pytest.raises(type(error)):
            runner.run(_request(), _analyst())
        events.extend(store.list_for_request(_REQUEST_ID))

    report = build_layer_metrics_report(_REQUEST_ID, tuple(events))

    assert report.event_count == len(events)
    tool = next(m for m in report.layers if m.layer is TraceErrorCategory.TOOL)
    assert tool.failure_count == len(_NODE_FAULTS)
    assert tool.success_rate == 0.0
