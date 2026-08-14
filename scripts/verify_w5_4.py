import json
from time import time_ns

import httpx

from retail_analytics_agent.approval import ApprovalAuditRecord
from retail_analytics_agent.audit import QueryAuditRecord, QueryAuditStatus
from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
)
from retail_analytics_agent.model_adapters import (
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
    AnalysisResultStatus,
)
from retail_analytics_agent.query_service import SafeQueryResult
from retail_analytics_agent.resilience import RetryPolicy
from retail_analytics_agent.tracing import (
    DatabaseExecutionTraceStore,
    TraceStatus,
    execution_trace_context,
)
from retail_analytics_agent.workflow import (
    build_analysis_graph,
    create_initial_state,
    create_workflow_nodes,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    SQLGlotValidationTool,
)


class NoopQueryAuditSink:
    def record(self, audit: QueryAuditRecord) -> None:
        return None


class NoopApprovalAuditSink:
    def record(self, audit: ApprovalAuditRecord) -> None:
        return None


class FixedExecutionTool:
    def execute(self, **kwargs) -> SafeQueryResult:
        return SafeQueryResult(
            rows=[
                {"channel": "淘宝", "sales_amount": "9000.00"},
                {"channel": "京东", "sales_amount": "800.00"},
            ],
            audit=QueryAuditRecord(
                request_id=kwargs["request_id"],
                user_id=kwargs["user_id"],
                original_sql=kwargs["original_sql"],
                executed_sql=kwargs["prepared_sql"].sql,
                status=QueryAuditStatus.SUCCEEDED,
                row_count=2,
                duration_ms=1,
            ),
        )


def _model_handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    system_prompt = payload["messages"][0]["content"]
    if "零售分析规划器" in system_prompt:
        content = {
            "analysis_goal": "统计最近 30 天各渠道销售额",
            "metrics": ["sales_amount"],
            "dimensions": ["channel"],
            "filters": [],
            "time_range_days": 30,
            "sort": [
                {"field": "sales_amount", "direction": "descending"}
            ],
            "limit": 10,
        }
    elif "只读 SQL 生成器" in system_prompt:
        content = {
            "sql": (
                "SELECT o.channel AS channel, "
                "SUM(oi.quantity * oi.unit_price) AS sales_amount "
                "FROM orders AS o JOIN order_items AS oi "
                "ON o.order_id = oi.order_id "
                "WHERE o.status = 'paid' "
                "AND o.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' "
                "GROUP BY o.channel ORDER BY sales_amount DESC LIMIT 10"
            )
        }
    else:
        content = {"answer": "该响应不会被使用。"}
    return httpx.Response(
        200,
        json={"message": {"content": json.dumps(content, ensure_ascii=False)}},
    )


def main() -> None:
    request_id = f"W5-4-TRACE-{time_ns()}"
    trace_store = DatabaseExecutionTraceStore()
    retry_policy = RetryPolicy(
        max_attempts=2,
        initial_backoff_seconds=0,
        max_backoff_seconds=0,
        jitter_ratio=0,
    )
    injector = ScriptedFaultInjector(
        (
            FaultRule(
                "model.summarize",
                1,
                httpx.ConnectTimeout("injected summary timeout one"),
            ),
            FaultRule(
                "model.summarize",
                2,
                httpx.ConnectTimeout("injected summary timeout two"),
            ),
        )
    )
    with httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(_model_handler),
    ) as client:
        nodes = create_workflow_nodes(
            planner=OllamaAnalysisPlanner(
                client,
                retry_policy=retry_policy,
            ),
            retrieval_tool=CatalogRetrievalTool(),
            sql_generator=OllamaSQLGenerator(
                client,
                retry_policy=retry_policy,
            ),
            validation_tool=SQLGlotValidationTool(NoopQueryAuditSink()),
            approval_audit_sink=NoopApprovalAuditSink(),
            execution_tool=FixedExecutionTool(),
            summarizer=OllamaResultSummarizer(
                client,
                retry_policy=retry_policy,
            ),
        )
        graph = build_analysis_graph(nodes)
        request = AnalysisRequest(
            request_id=request_id,
            user_id="USER-001",
            question="最近30天各渠道销售额是多少？",
            max_rows=10,
        )
        with (
            execution_trace_context(request_id, trace_store),
            fault_injection_context(injector),
        ):
            result = graph.invoke(
                create_initial_state(
                    request,
                    access_context=AccessContext(
                        user_id="USER-001",
                        role=AccessRole.ANALYST,
                    ),
                )
            )

    events = trace_store.list_for_request(request_id)
    summary_events = [
        event for event in events if event.component == "model.summarize"
    ]
    if result["result_status"] is not AnalysisResultStatus.DEGRADED:
        raise AssertionError("summary outage did not degrade the result")
    if len(result["query_rows"]) != 2:
        raise AssertionError("trusted query rows were not preserved")
    if [event.status for event in summary_events] != [
        TraceStatus.STARTED,
        TraceStatus.FAILED,
        TraceStatus.RETRY_SCHEDULED,
        TraceStatus.STARTED,
        TraceStatus.FAILED,
    ]:
        raise AssertionError(f"unexpected summary trace: {summary_events}")
    if not any(
        event.component == "node.summarize"
        and event.status is TraceStatus.DEGRADED
        for event in events
    ):
        raise AssertionError("workflow degradation was not traced")

    print(
        "W5-4 fault injection verification passed: deterministic summary "
        f"failure preserved 2 rows and recorded {len(events)} trace events "
        f"for {request_id}"
    )


if __name__ == "__main__":
    main()
