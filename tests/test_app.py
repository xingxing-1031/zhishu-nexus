from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.analysis_service import get_analysis_runner
from retail_analytics_agent.analysis_service import AnalysisRequestConflictError
from retail_analytics_agent.app import app
from retail_analytics_agent.database import get_database_connection
from retail_analytics_agent.model_adapters import ModelInvocationError
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisResponse,
    AnalysisRunningResponse,
    AnalysisStreamEvent,
    ApprovalRequiredResponse,
    ApprovalRejectedResponse,
)
from retail_analytics_agent.tracing import (
    ExecutionTraceEvent,
    ExecutionTraceResponse,
    InMemoryExecutionTraceStore,
    TraceStatus,
    execution_trace_context,
    record_execution_trace,
)


client = TestClient(app)


def _access_context() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _admin_access_context() -> AccessContext:
    return AccessContext(user_id="ADMIN-001", role=AccessRole.ADMIN)


def test_demo_homepage_and_static_assets_are_available() -> None:
    page = client.get("/")
    stylesheet = client.get("/static/demo.css")
    script = client.get("/static/demo.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "零售运营分析台" in page.text
    assert stylesheet.status_code == 200
    assert "--accent" in stylesheet.text
    assert script.status_code == 200
    assert 'fetch("/analysis/stream"' in script.text


def test_session_returns_server_configured_access_context() -> None:
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.get("/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "USER-001",
        "role": "analyst",
    }


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validate_analysis_request_accepts_valid_data() -> None:
    response = client.post(
        "/analysis/validate",
        json={
            "request_id": "REQ-001",
            "user_id": "USER-001",
            "question": "最近30天各渠道销售额是多少？",
        },
    )

    assert response.status_code == 200
    assert response.json()["request_id"] == "REQ-001"
    assert response.json()["max_rows"] == 100


def test_validate_analysis_request_rejects_too_many_rows() -> None:
    response = client.post(
        "/analysis/validate",
        json={
            "request_id": "REQ-002",
            "user_id": "USER-001",
            "question": "查询全部订单",
            "max_rows": 1001,
        },
    )

    assert response.status_code == 422

    error = response.json()["detail"][0]

    assert error["loc"] == ["body", "max_rows"]
    assert error["type"] == "less_than_equal"


def test_run_analysis_invokes_complete_workflow_runner() -> None:
    runner = Mock()
    runner.run.return_value = AnalysisResponse(
        request_id="REQ-RUN-001",
        access_role=AccessRole.ANALYST,
        answer="最近30天，京东渠道销售额为 11300.00 元。",
        plan={
            "analysis_goal": "各渠道销售额",
            "metrics": ["sales_amount"],
            "dimensions": ["channel"],
            "time_range": {"days": 30},
            "limit": 10,
        },
        rows=[{"channel": "京东", "sales_amount": "11300.00"}],
        chart_spec={
            "chart_type": "bar",
            "title": "各渠道销售额",
            "x_field": "channel",
            "y_fields": ["sales_amount"],
        },
        evidence_source_ids=(
            "metric.sales_amount.v1",
            "schema.orders",
        ),
        retry_count=0,
        trace=(
            "plan",
            "retrieve",
            "generate_sql",
            "validate_sql",
            "execute_sql",
            "summarize",
        ),
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/run",
            json={
                "request_id": "REQ-RUN-001",
                "user_id": "USER-001",
                "question": "最近30天各渠道销售额是多少？",
                "max_rows": 10,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["chart_spec"] == {
        "chart_type": "bar",
        "title": "各渠道销售额",
        "x_field": "channel",
        "y_fields": ["sales_amount"],
    }
    runner.run.assert_called_once()
    assert runner.run.call_args.args[1] == _access_context()


def test_run_analysis_returns_502_when_model_is_unavailable() -> None:
    runner = Mock()
    runner.run.side_effect = ModelInvocationError("Ollama unavailable")
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/run",
            json={
                "request_id": "REQ-RUN-002",
                "user_id": "USER-001",
                "question": "查询销售额",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json() == {"detail": "Ollama unavailable"}


def test_run_analysis_returns_202_for_duplicate_still_running() -> None:
    runner = Mock()
    runner.run.return_value = AnalysisRunningResponse(
        request_id="REQ-RUNNING-001",
        access_role=AccessRole.ANALYST,
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/run",
            json={
                "request_id": "REQ-RUNNING-001",
                "user_id": "USER-001",
                "question": "查询销售额",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "running"


def test_run_analysis_returns_409_for_reused_request_id() -> None:
    runner = Mock()
    runner.run.side_effect = AnalysisRequestConflictError(
        "request_id is already bound to different analysis input"
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/run",
            json={
                "request_id": "REQ-CONFLICT-001",
                "user_id": "USER-001",
                "question": "查询退款金额",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "different analysis input" in response.json()["detail"]


def test_stream_analysis_returns_sse_status_and_result_events() -> None:
    runner = Mock()
    runner.stream.return_value = [
        AnalysisStreamEvent(
            event="status",
            node="plan",
            message="正在理解分析问题",
        ),
        AnalysisStreamEvent(
            event="result",
            message="分析完成",
            response=AnalysisResponse(
                request_id="REQ-STREAM-001",
                access_role=AccessRole.ANALYST,
                answer="京东渠道销售额为 11300.00 元。",
                plan={
                    "analysis_goal": "各渠道销售额",
                    "metrics": ["sales_amount"],
                    "dimensions": ["channel"],
                },
                rows=[
                    {"channel": "京东", "sales_amount": "11300.00"}
                ],
                chart_spec={
                    "chart_type": "bar",
                    "title": "各渠道销售额",
                    "x_field": "channel",
                    "y_fields": ["sales_amount"],
                },
                evidence_source_ids=("metric.sales_amount.v1",),
                retry_count=0,
                trace=("plan", "summarize"),
            ),
        ),
    ]
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/stream",
            json={
                "request_id": "REQ-STREAM-001",
                "user_id": "USER-001",
                "question": "查询各渠道销售额",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status\n" in response.text
    assert '"node":"plan"' in response.text
    assert "event: result\n" in response.text
    assert "京东渠道销售额为 11300.00 元" in response.text
    runner.stream.assert_called_once()
    assert runner.stream.call_args.args[1] == _access_context()


def test_stream_analysis_keeps_contextvars_in_one_worker_context() -> None:
    trace_store = InMemoryExecutionTraceStore()
    runner = Mock()

    def stream_with_context():
        with execution_trace_context("REQ-STREAM-CONTEXT", trace_store):
            record_execution_trace("model.plan", TraceStatus.STARTED)
            yield AnalysisStreamEvent(
                event="status",
                node="plan",
                message="正在理解分析问题",
            )
            record_execution_trace("model.plan", TraceStatus.SUCCEEDED)

    runner.stream.side_effect = lambda *_: stream_with_context()
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/stream",
            json={
                "request_id": "REQ-STREAM-CONTEXT",
                "user_id": "USER-001",
                "question": "查询销售额",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "created in a different Context" not in response.text
    assert "event: status" in response.text
    assert [event.status for event in trace_store.list_for_request(
        "REQ-STREAM-CONTEXT"
    )] == [TraceStatus.STARTED, TraceStatus.SUCCEEDED]


def test_run_analysis_rejects_mismatched_trusted_identity() -> None:
    runner = Mock()
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/run",
            json={
                "request_id": "REQ-FORGED-001",
                "user_id": "USER-999",
                "question": "query sales amount",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {
        "detail": "request user_id does not match authenticated user"
    }
    runner.run.assert_not_called()


def test_run_analysis_returns_202_when_approval_is_required() -> None:
    runner = Mock()
    runner.run.return_value = ApprovalRequiredResponse(
        request_id="REQ-PENDING-001",
        access_role=AccessRole.ADMIN,
        sql="SELECT reason FROM refunds LIMIT 10",
        reasons=("query reads sensitive columns: refunds.reason",),
        sensitive_columns=("refunds.reason",),
        result_limit=10,
        trace=("plan", "validate_sql", "assess_risk"),
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _admin_access_context

    try:
        response = client.post(
            "/analysis/run",
            json={
                "request_id": "REQ-PENDING-001",
                "user_id": "ADMIN-001",
                "question": "查询退款原因",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["sensitive_columns"] == ["refunds.reason"]


def test_analyst_cannot_resolve_approval() -> None:
    runner = Mock()
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.post(
            "/analysis/REQ-PENDING-002/approval",
            json={"decision": "approve"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    runner.resume_approval.assert_not_called()


def test_admin_resolves_approval_and_returns_rejection() -> None:
    runner = Mock()
    runner.resume_approval.return_value = ApprovalRejectedResponse(
        request_id="REQ-PENDING-003",
        reviewed_by="ADMIN-001",
        reason="结果范围过大",
        trace=("assess_risk", "request_approval", "fail"),
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _admin_access_context

    try:
        response = client.post(
            "/analysis/REQ-PENDING-003/approval",
            json={
                "decision": "reject",
                "reason": "结果范围过大",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reviewed_by"] == "ADMIN-001"
    runner.resume_approval.assert_called_once()
    assert runner.resume_approval.call_args.args[1].decision.value == "reject"


def test_read_analysis_status_returns_persisted_pending_outcome() -> None:
    runner = Mock()
    runner.get_status.return_value = ApprovalRequiredResponse(
        request_id="REQ-PENDING-004",
        access_role=AccessRole.ADMIN,
        sql="SELECT reason FROM refunds LIMIT 10",
        reasons=("query reads sensitive columns: refunds.reason",),
        sensitive_columns=("refunds.reason",),
        result_limit=10,
        trace=("validate_sql", "assess_risk"),
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _admin_access_context

    try:
        response = client.get("/analysis/REQ-PENDING-004")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    runner.get_status.assert_called_once_with(
        "REQ-PENDING-004",
        _admin_access_context(),
    )


def test_read_analysis_trace_returns_structured_events() -> None:
    runner = Mock()
    runner.get_trace.return_value = ExecutionTraceResponse(
        request_id="REQ-TRACE-001",
        events=(
            ExecutionTraceEvent(
                request_id="REQ-TRACE-001",
                component="model.plan",
                status=TraceStatus.FAILED,
                attempt=1,
                duration_ms=120,
                error_type="HTTP_503",
                error_message="temporarily unavailable",
            ),
            ExecutionTraceEvent(
                request_id="REQ-TRACE-001",
                component="model.plan",
                status=TraceStatus.SUCCEEDED,
                attempt=2,
                duration_ms=80,
            ),
        ),
    )
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    app.dependency_overrides[get_access_context] = _access_context

    try:
        response = client.get("/analysis/REQ-TRACE-001/trace")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [event["status"] for event in response.json()["events"]] == [
        "failed",
        "succeeded",
    ]
    assert response.json()["events"][0]["error_type"] == "HTTP_503"
    runner.get_trace.assert_called_once_with(
        "REQ-TRACE-001",
        _access_context(),
    )


def test_channel_sales_summary_returns_query_results() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "channel": "京东",
            "paid_order_count": 2,
            "sales_amount": Decimal("11300.00"),
        }
    ]
    app.dependency_overrides[get_database_connection] = lambda: connection

    try:
        response = client.get("/analytics/channels?days=30")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "channel": "京东",
            "paid_order_count": 2,
            "sales_amount": "11300.00",
        }
    ]


def test_channel_sales_summary_rejects_invalid_days() -> None:
    app.dependency_overrides[get_database_connection] = lambda: Mock()

    try:
        response = client.get("/analytics/channels?days=0")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_product_sales_summary_returns_query_results() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "product_id": "PROD-001",
            "product_name": "Smartphone",
            "units_sold": 2,
            "sales_amount": Decimal("14000.00"),
        }
    ]
    app.dependency_overrides[get_database_connection] = lambda: connection

    try:
        response = client.get(
            "/analytics/products?days=30&limit=10"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "product_id": "PROD-001",
            "product_name": "Smartphone",
            "units_sold": 2,
            "sales_amount": "14000.00",
        }
    ]


def test_product_sales_summary_rejects_invalid_limit() -> None:
    app.dependency_overrides[get_database_connection] = lambda: Mock()

    try:
        response = client.get("/analytics/products?limit=0")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_refund_status_summary_returns_query_results() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "status": "completed",
            "refund_count": 2,
            "refund_amount": Decimal("1500.00"),
        }
    ]
    app.dependency_overrides[get_database_connection] = lambda: connection

    try:
        response = client.get("/analytics/refunds/statuses?days=30")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "status": "completed",
            "refund_count": 2,
            "refund_amount": "1500.00",
        }
    ]


def test_refund_status_summary_rejects_invalid_days() -> None:
    app.dependency_overrides[get_database_connection] = lambda: Mock()

    try:
        response = client.get("/analytics/refunds/statuses?days=0")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_order_status_summary_returns_query_results() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "status": "paid",
            "order_count": 4,
            "order_amount": Decimal("20900.00"),
        }
    ]
    app.dependency_overrides[get_database_connection] = lambda: connection

    try:
        response = client.get("/analytics/orders/statuses?days=30")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "status": "paid",
            "order_count": 4,
            "order_amount": "20900.00",
        }
    ]


def test_order_status_summary_rejects_invalid_days() -> None:
    app.dependency_overrides[get_database_connection] = lambda: Mock()

    try:
        response = client.get("/analytics/orders/statuses?days=366")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
