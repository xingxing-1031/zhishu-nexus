from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

from retail_analytics_agent.agent_models import (
    AgentRequest,
    AgentTaskStatus,
)
from retail_analytics_agent.agent_runs import InMemoryAgentRunStore
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.general_agent import GeneralAgentResult
from retail_analytics_agent.knowledge_adapter import KnowledgeEvidence
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisDimension,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisResultStatus,
)
from retail_analytics_agent.request_registry import (
    RequestClaim,
    RequestClaimStatus,
    RequestRunStatus,
)
from retail_analytics_agent.sql_safety import PreparedSQL
from retail_analytics_agent.supervisor import Supervisor
from retail_analytics_agent.tracing import (
    ExecutionTraceEvent,
    InMemoryExecutionTraceStore,
    TraceStatus,
    execution_trace_context,
    record_execution_trace,
)
from retail_analytics_agent.workflow import (
    AnalysisState,
    trace_workflow_node,
)
from retail_analytics_agent.zhishu_service import ZhishuAgentService


def _request(question: str, request_id: str = "r1") -> AgentRequest:
    return AgentRequest(
        request_id=request_id,
        conversation_id="c1",
        user_id="u1",
        question=question,
    )


def _access() -> AccessContext:
    return AccessContext(user_id="u1", role=AccessRole.ANALYST)


def _context_service() -> EnterpriseAgentService:
    return EnterpriseAgentService(
        analysis_runner=object(),
        context_builder=ContextBuilder(InMemoryConversationStore()),
        task_planner=object(),
    )


class FakeGeneral:
    def answer(self, *_args, **_kwargs) -> GeneralAgentResult:
        return GeneralAgentResult(
            status=AgentTaskStatus.SUCCEEDED,
            answer="普通回答",
        )


class FakeAnswerer:
    def answer(self, question, history, evidence, data=None):
        assert question
        assert history == []
        assert evidence
        return "基于已验证证据的结论。"


class FakeKnowledge:
    def retrieve(self, _query):
        return (
            KnowledgeEvidence(
                source_id="policy:refund@1.0",
                title="售后制度",
                version="1.0",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                quote="退款超过规则阈值需要人工复核。",
                score=0.95,
            ),
        )


def _last_event(
    events: tuple[ExecutionTraceEvent, ...],
    status: TraceStatus,
) -> ExecutionTraceEvent:
    return [event for event in events if event.status is status][-1]


def _claim() -> RequestClaim:
    return RequestClaim(
        status=RequestClaimStatus.EXISTING,
        run_status=RequestRunStatus.COMPLETED,
        user_id="u1",
        access_role=AccessRole.ANALYST,
    )


class TestTracePayloadField:
    def test_trace_event_carries_payload(self) -> None:
        event = ExecutionTraceEvent(
            request_id="r1",
            component="supervisor.route",
            status=TraceStatus.SUCCEEDED,
            payload={"mode": "data", "confidence": 0.9},
        )

        dumped = event.model_dump(mode="json")

        assert dumped["payload"] == {"mode": "data", "confidence": 0.9}

    def test_trace_event_payload_is_optional(self) -> None:
        event = ExecutionTraceEvent(
            request_id="r1",
            component="node.plan",
            status=TraceStatus.SUCCEEDED,
        )

        assert event.payload is None


class TestWorkflowNodeEvidence:
    def test_plan_node_payload_carries_structured_plan(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "plan",
            lambda _state: {
                "plan": AnalysisPlan(
                    analysis_goal="比较各渠道退款率",
                    metrics=[AnalysisMetric.REFUND_RATE],
                    dimensions=[AnalysisDimension.CHANNEL],
                    limit=50,
                ),
                "trace": ["plan"],
            },
        )

        with execution_trace_context("r1", store):
            node(cast(AnalysisState, {"request_id": "r1"}))

        event = _last_event(store.list_for_request("r1"), TraceStatus.SUCCEEDED)
        assert event.payload["goal"] == "比较各渠道退款率"
        assert event.payload["metrics"] == ["refund_rate"]
        assert event.payload["dimensions"] == ["channel"]
        assert event.payload["limit"] == 50

    def test_scope_node_payload_carries_dataset_identity(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "scope",
            lambda _state: {
                "dataset_name": "订单数据集",
                "dataset_schema": "sales_schema",
                "scope_supported": True,
                "scope_rejection_reason": None,
                "dataset_scope": SimpleNamespace(
                    metric_catalog=SimpleNamespace(definitions=(1, 2, 3))
                ),
                "trace": ["scope"],
            },
        )
        state = cast(
            AnalysisState,
            {"request_id": "r1", "dataset_id": "d1", "dataset_version": 3},
        )

        with execution_trace_context("r1", store):
            node(state)

        event = _last_event(store.list_for_request("r1"), TraceStatus.SUCCEEDED)
        assert event.payload["dataset_id"] == "d1"
        assert event.payload["dataset_version"] == 3
        assert event.payload["dataset_schema"] == "sales_schema"
        assert event.payload["dataset_name"] == "订单数据集"
        assert event.payload["metric_count"] == 3
        assert event.payload["scope_supported"] is True

    def test_scope_node_payload_omits_dataset_when_absent(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "scope",
            lambda _state: {
                "scope_supported": False,
                "scope_rejection_reason": "non_read_only",
                "trace": ["scope"],
            },
        )

        with execution_trace_context("r1", store):
            node(cast(AnalysisState, {"request_id": "r1"}))

        event = _last_event(store.list_for_request("r1"), TraceStatus.REJECTED)
        assert "dataset_schema" not in event.payload
        assert event.payload["scope_supported"] is False
        assert event.payload["scope_rejection_reason"] == "non_read_only"

    def test_validate_sql_node_payload_records_tables(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "validate_sql",
            lambda _state: {
                "prepared_sql": PreparedSQL(
                    sql="SELECT channel, refund_rate FROM refunds",
                    tables=("refunds",),
                    max_rows=100,
                ),
                "sql_valid": True,
                "sql_validation_error": None,
                "trace": ["validate_sql"],
            },
        )

        with execution_trace_context("r1", store):
            node(cast(AnalysisState, {"request_id": "r1"}))

        event = _last_event(store.list_for_request("r1"), TraceStatus.SUCCEEDED)
        assert event.payload["sql_valid"] is True
        assert event.payload["tables"] == ["refunds"]
        assert event.payload["result_limit"] == 100

    def test_execute_sql_node_payload_records_row_count(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "execute_sql",
            lambda _state: {
                "query_rows": [{"channel": "app"} for _ in range(3)],
                "execution_error": None,
                "trace": ["execute_sql"],
            },
        )

        with execution_trace_context("r1", store):
            node(cast(AnalysisState, {"request_id": "r1"}))

        event = _last_event(store.list_for_request("r1"), TraceStatus.SUCCEEDED)
        assert event.payload["row_count"] == 3
        assert event.payload["execution_error"] is None

    def test_summarize_node_payload_records_status(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "summarize",
            lambda _state: {
                "result_status": AnalysisResultStatus.SUCCEEDED,
                "degradation_reason": None,
                "final_answer": "结论文字",
                "trace": ["summarize"],
            },
        )

        with execution_trace_context("r1", store):
            node(cast(AnalysisState, {"request_id": "r1"}))

        event = _last_event(store.list_for_request("r1"), TraceStatus.SUCCEEDED)
        assert event.payload["result_status"] == "succeeded"
        assert event.payload["answer_chars"] == 4

    def test_summarize_degradation_payload_records_reason(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "summarize",
            lambda _state: {
                "result_status": AnalysisResultStatus.DEGRADED,
                "degradation_reason": "summarizer unavailable",
                "final_answer": "已返回数据",
                "trace": ["summarize"],
            },
        )

        with execution_trace_context("r1", store):
            node(cast(AnalysisState, {"request_id": "r1"}))

        event = _last_event(store.list_for_request("r1"), TraceStatus.DEGRADED)
        assert event.payload["degradation_reason"] == "summarizer unavailable"

    def test_fail_node_payload_records_failure_reason(self) -> None:
        store = InMemoryExecutionTraceStore()
        node = trace_workflow_node(
            "fail",
            lambda _state: {"final_answer": "分析失败", "trace": ["fail"]},
        )
        state = cast(AnalysisState, {"request_id": "r1", "execution_error": "timeout"})

        with execution_trace_context("r1", store):
            node(state)

        event = _last_event(store.list_for_request("r1"), TraceStatus.FAILED)
        assert event.payload["failure_reason"] == "timeout"


class TestTraceRedaction:
    def test_analyst_trace_redacts_dataset_schema(self) -> None:
        request_store = Mock()
        request_store.get.return_value = _claim()
        trace_store = InMemoryExecutionTraceStore()
        with execution_trace_context("r1", trace_store):
            record_execution_trace(
                "node.scope",
                TraceStatus.SUCCEEDED,
                payload={
                    "dataset_id": "d1",
                    "dataset_schema": "sales_schema",
                    "dataset_name": "订单数据集",
                    "scope_supported": True,
                    "scope_rejection_reason": None,
                },
            )
        runner = LangGraphAnalysisRunner(
            Mock(),
            request_store=request_store,
            trace_store=trace_store,
        )

        trace = runner.get_trace("r1", _access())

        payload = trace.events[0].payload
        assert payload["dataset_schema"] is None
        assert payload["dataset_name"] == "订单数据集"
        assert payload["dataset_id"] == "d1"

    def test_admin_trace_keeps_dataset_schema(self) -> None:
        request_store = Mock()
        request_store.get.return_value = _claim()
        trace_store = InMemoryExecutionTraceStore()
        with execution_trace_context("r1", trace_store):
            record_execution_trace(
                "node.scope",
                TraceStatus.SUCCEEDED,
                payload={
                    "dataset_id": "d1",
                    "dataset_schema": "sales_schema",
                    "scope_supported": True,
                    "scope_rejection_reason": None,
                },
            )
        runner = LangGraphAnalysisRunner(
            Mock(),
            request_store=request_store,
            trace_store=trace_store,
        )

        trace = runner.get_trace(
            "r1",
            AccessContext(user_id="admin", role=AccessRole.ADMIN),
        )

        assert trace.events[0].payload["dataset_schema"] == "sales_schema"


class TestZhishuTraceEvidence:
    def _service(self) -> tuple[ZhishuAgentService, InMemoryExecutionTraceStore]:
        trace_store = InMemoryExecutionTraceStore()
        service = ZhishuAgentService(
            data_agent=_context_service(),
            supervisor=Supervisor(),
            general_agent=FakeGeneral(),
            knowledge=FakeKnowledge(),
            answerer=FakeAnswerer(),
            run_store=InMemoryAgentRunStore(),
            trace_store=trace_store,
        )
        return service, trace_store

    def test_records_routing_and_context_evidence(self) -> None:
        service, trace_store = self._service()

        service.run(_request("公司的售后制度是什么"), _access())

        events = trace_store.list_for_request("r1")
        route = next(e for e in events if e.component == "supervisor.route")
        context = next(e for e in events if e.component == "agent.context")
        assert route.payload["mode"] == "knowledge"
        assert route.payload["reason_code"] == "keyword_route"
        assert route.payload["confidence"] == 0.9
        assert route.payload["refused"] is False
        assert route.payload["agents"] == ["knowledge_agent", "review_agent"]
        assert "token_budget" in context.payload
        assert "token_estimate" in context.payload
        assert "truncated" in context.payload
        assert context.payload["task_goal"] == "公司的售后制度是什么"

    def test_refused_request_records_rejected_route(self) -> None:
        service, trace_store = self._service()

        service.run(_request("帮我删除订单数据"), _access())

        route = next(
            e for e in trace_store.list_for_request("r1")
            if e.component == "supervisor.route"
        )
        assert route.status is TraceStatus.REJECTED
        assert route.payload["refused"] is True
        assert route.payload["reason_code"] == "write_operation_refused"

    def test_ambiguous_request_records_pending_route(self) -> None:
        service, trace_store = self._service()

        service.run(_request("哪个渠道最好"), _access())

        route = next(
            e for e in trace_store.list_for_request("r1")
            if e.component == "supervisor.route"
        )
        assert route.status is TraceStatus.PENDING
        assert route.payload["missing_information"]

    def test_data_request_forwards_dataset_identity(self) -> None:
        service, trace_store = self._service()
        request = _request("分析销售额").model_copy(
            update={"dataset_id": "d1", "dataset_version": 2}
        )

        service.run(request, _access())

        route = next(
            e for e in trace_store.list_for_request("r1")
            if e.component == "supervisor.route"
        )
        assert route.payload["dataset_id"] == "d1"
        assert route.payload["dataset_version"] == 2
