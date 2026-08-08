from pathlib import Path
from unittest.mock import Mock, patch

from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
)
from retail_analytics_agent.request_registry import (
    CLAIM_REQUEST_SQL,
    MARK_REQUEST_SQL,
    DatabaseAnalysisRequestStore,
    RequestClaimStatus,
    RequestRunStatus,
    request_fingerprint,
)


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "migrations"
    / "005_resilience_and_idempotency.sql"
)


def _request(question: str = "查询销售额") -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-IDEMPOTENT-001",
        user_id="USER-001",
        question=question,
        max_rows=10,
    )


def _context() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _connection_context(connection: Mock) -> Mock:
    manager = Mock()
    manager.__enter__ = Mock(return_value=connection)
    manager.__exit__ = Mock(return_value=False)
    return manager


def test_request_fingerprint_changes_when_business_input_changes() -> None:
    first = request_fingerprint(_request(), _context())
    repeated = request_fingerprint(_request(), _context())
    changed = request_fingerprint(_request("查询退款金额"), _context())

    assert first == repeated
    assert first != changed
    assert len(first) == 64


def test_database_request_store_claims_new_request_atomically() -> None:
    connection = Mock()
    fingerprint = request_fingerprint(_request(), _context())
    connection.execute.return_value.fetchone.return_value = {
        "claim_status": "new",
        "request_fingerprint": fingerprint,
        "user_id": "USER-001",
        "access_role": "analyst",
        "status": "running",
        "error": None,
    }

    with patch(
        "retail_analytics_agent.request_registry.connect_to_database",
        return_value=_connection_context(connection),
    ):
        claim = DatabaseAnalysisRequestStore().claim(_request(), _context())

    assert claim.status is RequestClaimStatus.NEW
    assert claim.run_status is RequestRunStatus.RUNNING
    assert "ON CONFLICT (request_id) DO NOTHING" in CLAIM_REQUEST_SQL
    params = connection.execute.call_args.args[1]
    assert params["original_question"] == "查询销售额"
    assert params["max_rows"] == 10


def test_database_request_store_detects_reused_id_with_new_input() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {
        "claim_status": "existing",
        "request_fingerprint": request_fingerprint(_request(), _context()),
        "user_id": "USER-001",
        "access_role": "analyst",
        "status": "completed",
        "error": None,
    }

    with patch(
        "retail_analytics_agent.request_registry.connect_to_database",
        return_value=_connection_context(connection),
    ):
        claim = DatabaseAnalysisRequestStore().claim(
            _request("查询退款金额"),
            _context(),
        )

    assert claim.status is RequestClaimStatus.CONFLICT


def test_database_request_store_marks_terminal_status() -> None:
    connection = Mock()
    connection.execute.return_value.rowcount = 1

    with patch(
        "retail_analytics_agent.request_registry.connect_to_database",
        return_value=_connection_context(connection),
    ):
        DatabaseAnalysisRequestStore().mark(
            "REQ-IDEMPOTENT-001",
            RequestRunStatus.DEGRADED,
        )

    connection.execute.assert_called_once_with(
        MARK_REQUEST_SQL,
        {
            "request_id": "REQ-IDEMPOTENT-001",
            "status": "degraded",
            "error": None,
        },
    )


def test_resilience_migration_adds_database_idempotency_guards() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "uq_query_audit_event_key" in migration
    assert "uq_query_approval_event_key" in migration
    assert "CREATE TABLE analysis_request_registry" in migration
    assert "request_id TEXT PRIMARY KEY" in migration
    assert "request_fingerprint CHAR(64) NOT NULL" in migration
