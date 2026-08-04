from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from retail_analytics_agent.approval import (
    APPROVAL_AUDIT_INSERT_SQL,
    ApprovalAuditRecord,
    ApprovalAuditStatus,
    DatabaseApprovalAuditSink,
    assess_query_risk,
)
from retail_analytics_agent.models import (
    AccessRole,
    ApprovalResolutionRequest,
)
from retail_analytics_agent.sql_safety import prepare_safe_sql


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "migrations"
    / "004_query_approval_logs.sql"
)


def test_approval_migration_defines_auditable_status_constraints() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "CREATE TABLE query_approval_logs" in migration
    assert "status IN ('pending', 'approved', 'rejected')" in migration
    assert "access_role IN ('analyst', 'admin')" in migration
    assert "cardinality(reasons) > 0" in migration
    assert "CREATE INDEX idx_query_approval_request_id" in migration


def test_sensitive_admin_query_requires_approval() -> None:
    prepared = prepare_safe_sql(
        "SELECT r.reason FROM refunds AS r LIMIT 10",
        max_rows=10,
        access_role=AccessRole.ADMIN,
    )

    risk = assess_query_risk(prepared)

    assert risk.requires_approval is True
    assert risk.sensitive_columns == ("refunds.reason",)
    assert risk.result_limit == 10


def test_large_result_limit_requires_approval() -> None:
    prepared = prepare_safe_sql(
        "SELECT order_id FROM orders",
        max_rows=101,
    )

    risk = assess_query_risk(prepared)

    assert risk.requires_approval is True
    assert risk.sensitive_columns == ()
    assert "exceeds 100" in risk.reasons[0]


def test_explicit_small_limit_avoids_large_result_approval() -> None:
    prepared = prepare_safe_sql(
        "SELECT order_id FROM orders LIMIT 10",
        max_rows=500,
    )

    risk = assess_query_risk(prepared)

    assert prepared.result_limit == 10
    assert risk.requires_approval is False


def test_rejection_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="rejection reason is required"):
        ApprovalResolutionRequest(decision="reject")


def test_database_approval_audit_sink_persists_event() -> None:
    connection = Mock()
    context_manager = Mock()
    context_manager.__enter__ = Mock(return_value=connection)
    context_manager.__exit__ = Mock(return_value=False)
    audit = ApprovalAuditRecord(
        request_id="REQ-APPROVAL-001",
        requester_id="USER-001",
        access_role=AccessRole.ADMIN,
        sql="SELECT reason FROM refunds LIMIT 10",
        status=ApprovalAuditStatus.PENDING,
        reasons=("query reads sensitive columns: refunds.reason",),
    )

    with patch(
        "retail_analytics_agent.approval.connect_to_database",
        return_value=context_manager,
    ):
        DatabaseApprovalAuditSink().record(audit)

    payload = audit.model_dump(mode="json")
    payload["reasons"] = list(audit.reasons)
    connection.execute.assert_called_once_with(
        APPROVAL_AUDIT_INSERT_SQL,
        payload,
    )
