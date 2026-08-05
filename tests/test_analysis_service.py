from unittest.mock import Mock

import pytest

from retail_analytics_agent.analysis_service import (
    AnalysisRequestConflictError,
    AnalysisRunError,
    LangGraphAnalysisRunner,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    ApprovalResolutionRequest,
    ApprovalRequiredResponse,
    ApprovalStatus,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisResultStatus,
    AnalysisRunningResponse,
    ChartSpec,
    QueryRisk,
)
from retail_analytics_agent.request_registry import (
    RequestClaim,
    RequestClaimStatus,
    RequestRunStatus,
)
from retail_analytics_agent.sql_safety import prepare_safe_sql
from retail_analytics_agent.tracing import (
    ExecutionTraceEvent,
    InMemoryExecutionTraceStore,
    TraceStatus,
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


def _admin_context() -> AccessContext:
    return AccessContext(user_id="ADMIN-001", role=AccessRole.ADMIN)


def _pending_state():
    state = create_initial_state(
        AnalysisRequest(
            request_id="REQ-PENDING-001",
            user_id="ADMIN-001",
            question="查询退款原因",
            max_rows=10,
        ),
        access_context=_admin_context(),
    )
    state.update(
        {
            "prepared_sql": prepare_safe_sql(
                "SELECT reason FROM refunds LIMIT 10",
                max_rows=10,
                access_role=AccessRole.ADMIN,
            ),
            "sql_valid": True,
            "query_risk": QueryRisk(
                requires_approval=True,
                reasons=(
                    "query reads sensitive columns: refunds.reason",
                ),
                sensitive_columns=("refunds.reason",),
                result_limit=10,
            ),
            "approval_status": ApprovalStatus.PENDING,
            "trace": ["plan", "validate_sql", "assess_risk"],
        }
    )
    return state


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


def test_runner_returns_pending_approval_outcome() -> None:
    graph = Mock()
    graph.invoke.return_value = _pending_state()
    runner = LangGraphAnalysisRunner(graph)
    request = AnalysisRequest(
        request_id="REQ-PENDING-001",
        user_id="ADMIN-001",
        question="查询退款原因",
        max_rows=10,
    )

    outcome = runner.run(request, _admin_context())

    assert isinstance(outcome, ApprovalRequiredResponse)
    assert outcome.status is ApprovalStatus.PENDING
    assert outcome.sensitive_columns == ("refunds.reason",)


def test_runner_resumes_pending_approval_with_trusted_admin() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(
        values=_pending_state(),
        next=("request_approval",),
    )
    completed = _successful_state()
    completed["request_id"] = "REQ-PENDING-001"
    completed["user_id"] = "ADMIN-001"
    completed["access_role"] = AccessRole.ADMIN
    completed["approval_status"] = ApprovalStatus.APPROVED
    completed["reviewed_by"] = "ADMIN-REVIEWER"
    graph.invoke.return_value = completed
    runner = LangGraphAnalysisRunner(graph)

    outcome = runner.resume_approval(
        "REQ-PENDING-001",
        ApprovalResolutionRequest(decision="approve"),
        AccessContext(
            user_id="ADMIN-REVIEWER",
            role=AccessRole.ADMIN,
        ),
    )

    assert outcome.request_id == "REQ-PENDING-001"
    graph.get_state.assert_called_once()
    graph.invoke.assert_called_once()


def test_runner_refuses_analyst_approval_resolution() -> None:
    with pytest.raises(
        PermissionError,
        match="only an admin can resolve approvals",
    ):
        LangGraphAnalysisRunner(Mock()).resume_approval(
            "REQ-PENDING-001",
            ApprovalResolutionRequest(decision="approve"),
            _access_context(),
        )


def test_runner_stream_surfaces_pending_approval_event() -> None:
    graph = Mock()
    graph.stream.return_value = [_pending_state()]
    request = AnalysisRequest(
        request_id="REQ-PENDING-001",
        user_id="ADMIN-001",
        question="查询退款原因",
        max_rows=10,
    )

    events = list(
        LangGraphAnalysisRunner(graph).stream(request, _admin_context())
    )

    assert events[-1].event.value == "approval_required"
    assert events[-1].approval is not None
    assert events[-1].approval.request_id == "REQ-PENDING-001"


def test_runner_reads_persisted_pending_status_for_requester() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values=_pending_state())

    outcome = LangGraphAnalysisRunner(graph).get_status(
        "REQ-PENDING-001",
        _admin_context(),
    )

    assert isinstance(outcome, ApprovalRequiredResponse)
    assert outcome.status is ApprovalStatus.PENDING


def test_runner_hides_another_users_request_from_analyst() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values=_pending_state())

    with pytest.raises(
        PermissionError,
        match="analysis request belongs to another user",
    ):
        LangGraphAnalysisRunner(graph).get_status(
            "REQ-PENDING-001",
            AccessContext(
                user_id="USER-OTHER",
                role=AccessRole.ANALYST,
            ),
        )


def _claim(
    status: RequestClaimStatus,
    run_status: RequestRunStatus,
    *,
    error: str | None = None,
) -> RequestClaim:
    return RequestClaim(
        status=status,
        run_status=run_status,
        user_id="USER-001",
        access_role=AccessRole.ANALYST,
        error=error,
    )


def test_runner_returns_existing_completed_request_without_reinvoking() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(
        values=_successful_state(),
        next=(),
    )
    store = Mock()
    store.claim.return_value = _claim(
        RequestClaimStatus.EXISTING,
        RequestRunStatus.COMPLETED,
    )

    outcome = LangGraphAnalysisRunner(graph, request_store=store).run(
        _request(),
        _access_context(),
    )

    assert outcome.status is AnalysisResultStatus.SUCCEEDED
    graph.invoke.assert_not_called()


def test_runner_returns_running_for_duplicate_before_first_checkpoint() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values={}, next=())
    store = Mock()
    store.claim.return_value = _claim(
        RequestClaimStatus.EXISTING,
        RequestRunStatus.RUNNING,
    )

    outcome = LangGraphAnalysisRunner(graph, request_store=store).run(
        _request(),
        _access_context(),
    )

    assert isinstance(outcome, AnalysisRunningResponse)
    graph.invoke.assert_not_called()


def test_runner_rejects_request_id_reused_for_different_input() -> None:
    store = Mock()
    store.claim.return_value = _claim(
        RequestClaimStatus.CONFLICT,
        RequestRunStatus.RUNNING,
    )

    with pytest.raises(
        AnalysisRequestConflictError,
        match="different analysis input",
    ):
        LangGraphAnalysisRunner(Mock(), request_store=store).run(
            _request(),
            _access_context(),
        )


def test_runner_marks_degraded_result_in_request_registry() -> None:
    graph = Mock()
    state = _successful_state()
    state["result_status"] = AnalysisResultStatus.DEGRADED
    state["degradation_reason"] = "summary unavailable"
    graph.invoke.return_value = state
    store = Mock()
    store.claim.return_value = _claim(
        RequestClaimStatus.NEW,
        RequestRunStatus.RUNNING,
    )

    outcome = LangGraphAnalysisRunner(graph, request_store=store).run(
        _request(),
        _access_context(),
    )

    assert outcome.status is AnalysisResultStatus.DEGRADED
    store.mark.assert_called_once_with(
        "REQ-SERVICE-001",
        RequestRunStatus.DEGRADED,
        error=None,
    )


def test_runner_returns_trace_to_request_owner() -> None:
    request_store = Mock()
    request_store.get.return_value = _claim(
        RequestClaimStatus.EXISTING,
        RequestRunStatus.COMPLETED,
    )
    trace_store = InMemoryExecutionTraceStore()
    trace_store.record(
        ExecutionTraceEvent(
            request_id="REQ-SERVICE-001",
            component="node.plan",
            status=TraceStatus.SUCCEEDED,
            duration_ms=5,
        )
    )
    runner = LangGraphAnalysisRunner(
        Mock(),
        request_store=request_store,
        trace_store=trace_store,
    )

    response = runner.get_trace("REQ-SERVICE-001", _access_context())

    assert response.request_id == "REQ-SERVICE-001"
    assert response.events[0].component == "node.plan"
    assert response.events[0].duration_ms == 5


def test_runner_hides_trace_from_another_analyst() -> None:
    request_store = Mock()
    request_store.get.return_value = _claim(
        RequestClaimStatus.EXISTING,
        RequestRunStatus.COMPLETED,
    )
    runner = LangGraphAnalysisRunner(Mock(), request_store=request_store)

    with pytest.raises(
        PermissionError,
        match="analysis request belongs to another user",
    ):
        runner.get_trace(
            "REQ-SERVICE-001",
            AccessContext(user_id="USER-OTHER", role=AccessRole.ANALYST),
        )
