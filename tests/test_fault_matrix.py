from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.checkpoint_meta import (
    CheckpointMeta,
    InMemoryCheckpointMetaStore,
)
from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
)
from retail_analytics_agent.model_adapters import (
    ModelInvocationError,
    StructuredSQLGenerator,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisResultStatus,
    ApprovalResolutionRequest,
    ApprovalStatus,
    QueryRisk,
    RetrievalEvidence,
)
from retail_analytics_agent.request_registry import (
    RequestClaim,
    RequestClaimStatus,
    RequestRunStatus,
)
from retail_analytics_agent.resilience import RetryPolicy
from retail_analytics_agent.tracing import (
    InMemoryExecutionTraceStore,
    TraceErrorCategory,
    TraceStatus,
    execution_trace_context,
)
from retail_analytics_agent.workflow import (
    WorkflowNodes,
    build_analysis_graph,
    create_initial_state,
    create_summarize_node,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalToolError,
    SQLBusinessConsistencyToolError,
    SQLExecutionToolError,
    SQLValidationToolError,
)

pytestmark = pytest.mark.fault_injection

_REQUEST_ID = "REQ-FAULT-001"


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id=_REQUEST_ID,
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )


def _analyst() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _admin() -> AccessContext:
    return AccessContext(user_id="ADMIN-001", role=AccessRole.ADMIN)


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        limit=10,
    )


def _successful_state() -> dict:
    state = create_initial_state(_request())
    state.update(
        {
            "plan": _plan(),
            "sql_valid": True,
            "query_rows": [{"channel": "京东", "sales_amount": "11300.00"}],
            "final_answer": "京东渠道销售额为 11300.00 元。",
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


def _pending_state() -> dict:
    state = create_initial_state(_request())
    state.update(
        {
            "approval_status": ApprovalStatus.PENDING,
            "trace": ["plan", "validate_sql", "assess_risk"],
        }
    )
    return state


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


# --- A. 节点级故障：停止节点 + Trace 归因 ---------------------------------

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


@pytest.mark.parametrize(
    ("fault_name", "node_name", "error", "expected_category"),
    _NODE_FAULTS,
    ids=[case[0] for case in _NODE_FAULTS],
)
def test_node_fault_stops_at_injected_node_with_attribution(
    fault_name: str,
    node_name: str,
    error: Exception,
    expected_category: TraceErrorCategory,
) -> None:
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

    failed = [
        event
        for event in store.list_for_request(_REQUEST_ID)
        if event.status is TraceStatus.FAILED
    ]
    assert failed, f"{fault_name}: expected a FAILED trace event"
    event = failed[-1]
    assert event.node == node_name, fault_name
    assert event.attempt == 1, fault_name
    assert event.error_category is expected_category, fault_name


# --- B. 模型层故障：按策略重试 / 不重试 -----------------------------------


def _mock_chat_client(content: str = '{"sql": "SELECT 1"}') -> Mock:
    client = Mock()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"message": {"content": content}}
    client.post.return_value = response
    return client


def _no_delay_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_backoff_seconds=0,
        max_backoff_seconds=0,
        jitter_ratio=0,
    )


def _evidence() -> list[RetrievalEvidence]:
    return [
        RetrievalEvidence(source_id="schema.orders", content="orders.channel")
    ]


def test_model_timeout_retries_then_succeeds() -> None:
    client = _mock_chat_client()
    adapter = StructuredSQLGenerator(
        client=client,
        retry_policy=_no_delay_policy(),
    )
    store = InMemoryExecutionTraceStore()
    injector = ScriptedFaultInjector(
        (
            FaultRule(
                "model.generate_sql",
                1,
                httpx.TimeoutException("model timed out"),
            ),
        )
    )

    with fault_injection_context(injector), execution_trace_context(
        _REQUEST_ID,
        store,
        run_id="RUN-M1",
    ):
        sql = adapter.generate(
            question="各渠道销售额",
            plan=_plan(),
            evidence=_evidence(),
            access_role=AccessRole.ANALYST,
        )

    assert sql == "SELECT 1"
    events = store.list_for_request(_REQUEST_ID)
    assert [event.status for event in events] == [
        TraceStatus.STARTED,
        TraceStatus.FAILED,
        TraceStatus.RETRY_SCHEDULED,
        TraceStatus.STARTED,
        TraceStatus.SUCCEEDED,
    ]
    failed = next(
        event for event in events if event.status is TraceStatus.FAILED
    )
    assert failed.error_category is TraceErrorCategory.MODEL
    assert failed.attempt == 1
    assert client.post.call_count == 1


def test_model_invalid_json_fails_without_retry() -> None:
    client = _mock_chat_client()
    adapter = StructuredSQLGenerator(
        client=client,
        retry_policy=_no_delay_policy(),
    )
    store = InMemoryExecutionTraceStore()
    injector = ScriptedFaultInjector(
        (
            FaultRule(
                "model.generate_sql",
                1,
                ValueError("model returned invalid json"),
            ),
        )
    )

    with pytest.raises(ModelInvocationError):
        with fault_injection_context(injector), execution_trace_context(
            _REQUEST_ID,
            store,
        ):
            adapter.generate(
                question="各渠道销售额",
                plan=_plan(),
                evidence=_evidence(),
                access_role=AccessRole.ANALYST,
            )

    events = store.list_for_request(_REQUEST_ID)
    failed = [
        event for event in events if event.status is TraceStatus.FAILED
    ]
    assert len(failed) == 1
    assert failed[0].attempt == 1
    assert failed[0].error_category is TraceErrorCategory.MODEL
    assert client.post.call_count == 0


# --- C. 恢复/幂等型 ------------------------------------------------------


def test_checkpoint_corrupted_is_rejected() -> None:
    graph = Mock()
    meta = InMemoryCheckpointMetaStore()
    meta.save(
        CheckpointMeta(
            request_id=_REQUEST_ID,
            user_id="USER-001",
            state_version=0,
        )
    )

    with pytest.raises(
        RuntimeError,
        match="checkpoint state version mismatch",
    ):
        LangGraphAnalysisRunner(graph, checkpoint_meta=meta).run(
            _request(),
            _analyst(),
        )

    graph.invoke.assert_not_called()


def test_approval_resume_duplicate_is_idempotent() -> None:
    graph = Mock()
    graph.get_state.side_effect = [
        SimpleNamespace(values=_pending_state(), next=("request_approval",)),
        SimpleNamespace(
            values={
                **_pending_state(),
                "approval_status": ApprovalStatus.APPROVED,
            },
            next=(),
        ),
    ]
    graph.invoke.return_value = _successful_state()
    runner = LangGraphAnalysisRunner(graph)
    resolution = ApprovalResolutionRequest(decision="approve", reason="ok")

    runner.resume_approval(_REQUEST_ID, resolution, _admin())

    with pytest.raises(ValueError, match="approval request is not pending"):
        runner.resume_approval(_REQUEST_ID, resolution, _admin())

    graph.invoke.assert_called_once()


def test_sse_disconnect_reuses_existing_result() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values=_successful_state(), next=())
    store = Mock()
    store.claim.return_value = RequestClaim(
        status=RequestClaimStatus.EXISTING,
        run_status=RequestRunStatus.COMPLETED,
        user_id="USER-001",
        access_role=AccessRole.ANALYST,
    )

    outcome = LangGraphAnalysisRunner(graph, request_store=store).run(
        _request(),
        _analyst(),
    )

    assert outcome.status is AnalysisResultStatus.SUCCEEDED
    graph.invoke.assert_not_called()


# --- D. 成功分支保留 / partial_success ------------------------------------


def test_summarize_degrades_but_preserves_query_rows() -> None:
    summarizer = Mock()
    summarizer.summarize.side_effect = ModelInvocationError(
        "summary service unavailable"
    )
    state = create_initial_state(_request())
    state["plan"] = _plan()
    state["query_rows"] = [{"channel": "jd", "sales_amount": "9000.00"}]

    update = create_summarize_node(summarizer)(state)

    assert update["result_status"] is AnalysisResultStatus.DEGRADED
    assert update["degradation_reason"] == "summary service unavailable"
    assert "返回 1 行数据" in update["final_answer"]
    assert state["query_rows"] == [
        {"channel": "jd", "sales_amount": "9000.00"}
    ]
