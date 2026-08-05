from unittest.mock import Mock, patch

from retail_analytics_agent.audit import (
    AUDIT_INSERT_SQL,
    DatabaseAuditSink,
    QueryAuditRecord,
    QueryAuditStatus,
    query_audit_event_key,
)


def test_database_audit_sink_persists_structured_record() -> None:
    connection = Mock()
    context_manager = Mock()
    context_manager.__enter__ = Mock(return_value=connection)
    context_manager.__exit__ = Mock(return_value=False)
    audit = QueryAuditRecord(
        request_id="REQ-001",
        user_id="USER-001",
        original_sql="SELECT order_id FROM orders",
        executed_sql="SELECT order_id FROM orders LIMIT 10",
        status=QueryAuditStatus.SUCCEEDED,
        row_count=2,
        duration_ms=1.25,
    )

    with patch(
        "retail_analytics_agent.audit.connect_to_database",
        return_value=context_manager,
    ):
        DatabaseAuditSink().record(audit)

    payload = audit.model_dump(mode="json")
    payload["event_key"] = query_audit_event_key(audit)
    connection.execute.assert_called_once_with(AUDIT_INSERT_SQL, payload)


def test_query_audit_event_key_ignores_replay_duration() -> None:
    first = QueryAuditRecord(
        request_id="REQ-REPLAY-001",
        user_id="USER-001",
        original_sql="SELECT order_id FROM orders",
        executed_sql="SELECT order_id FROM orders LIMIT 10",
        status=QueryAuditStatus.SUCCEEDED,
        row_count=2,
        duration_ms=1.25,
    )
    replay = first.model_copy(update={"duration_ms": 9.75})

    assert query_audit_event_key(first) == query_audit_event_key(replay)
    assert "ON CONFLICT (event_key) DO NOTHING" in AUDIT_INSERT_SQL
