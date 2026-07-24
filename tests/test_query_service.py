from unittest.mock import Mock, call

import pytest

from retail_analytics_agent.audit import QueryAuditStatus
from retail_analytics_agent.query_service import (
    SET_STATEMENT_TIMEOUT_SQL,
    SET_TRANSACTION_READ_ONLY_SQL,
    execute_safe_query,
)
from retail_analytics_agent.sql_safety import SQLSafetyError


def test_execute_safe_query_applies_guards_and_audits_success() -> None:
    connection = Mock()
    result_cursor = Mock()
    result_cursor.fetchall.return_value = [
        {"order_id": "ORD-001"},
        {"order_id": "ORD-002"},
    ]
    connection.execute.side_effect = [Mock(), Mock(), result_cursor]
    audit_sink = Mock()

    result = execute_safe_query(
        connection,
        audit_sink,
        request_id="REQ-001",
        user_id="USER-001",
        sql="SELECT order_id FROM orders",
        max_rows=2,
        statement_timeout_ms=1500,
    )

    assert connection.execute.call_args_list == [
        call(SET_TRANSACTION_READ_ONLY_SQL),
        call(
            SET_STATEMENT_TIMEOUT_SQL,
            {"statement_timeout": "1500ms"},
        ),
        call("SELECT order_id FROM orders LIMIT 2"),
    ]
    assert result.rows == [
        {"order_id": "ORD-001"},
        {"order_id": "ORD-002"},
    ]
    assert result.audit.status is QueryAuditStatus.SUCCEEDED
    assert result.audit.row_count == 2
    assert result.audit.executed_sql.endswith("LIMIT 2")
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    audit_sink.record.assert_called_once_with(result.audit)


def test_execute_safe_query_audits_policy_rejection_without_database() -> None:
    connection = Mock()
    audit_sink = Mock()

    with pytest.raises(
        SQLSafetyError,
        match="wildcard columns are not allowed",
    ):
        execute_safe_query(
            connection,
            audit_sink,
            request_id="REQ-002",
            user_id="USER-001",
            sql="SELECT * FROM orders",
        )

    connection.execute.assert_not_called()
    audit = audit_sink.record.call_args.args[0]
    assert audit.status is QueryAuditStatus.REJECTED
    assert audit.executed_sql is None
    assert audit.row_count is None


def test_execute_safe_query_rolls_back_and_audits_database_failure() -> None:
    connection = Mock()
    connection.execute.side_effect = [
        Mock(),
        Mock(),
        RuntimeError("query timed out"),
    ]
    audit_sink = Mock()

    with pytest.raises(RuntimeError, match="query timed out"):
        execute_safe_query(
            connection,
            audit_sink,
            request_id="REQ-003",
            user_id="USER-001",
            sql="SELECT order_id FROM orders",
        )

    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    audit = audit_sink.record.call_args.args[0]
    assert audit.status is QueryAuditStatus.FAILED
    assert audit.executed_sql.endswith("LIMIT 100")
    assert audit.reason == "RuntimeError: query timed out"


@pytest.mark.parametrize("statement_timeout_ms", [99, 30001])
def test_execute_safe_query_rejects_invalid_timeout(
    statement_timeout_ms: int,
) -> None:
    connection = Mock()
    audit_sink = Mock()

    with pytest.raises(
        ValueError,
        match="statement_timeout_ms must be between 100 and 30000",
    ):
        execute_safe_query(
            connection,
            audit_sink,
            request_id="REQ-004",
            user_id="USER-001",
            sql="SELECT order_id FROM orders",
            statement_timeout_ms=statement_timeout_ms,
        )

    connection.execute.assert_not_called()
    audit = audit_sink.record.call_args.args[0]
    assert audit.status is QueryAuditStatus.REJECTED
