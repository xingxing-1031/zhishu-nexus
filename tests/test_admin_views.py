from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import SecretStr

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.admin_views import (
    ADMIN_AUDIT_SELECT_SQL,
    AdminAuditStatus,
    list_admin_audit_entries,
    list_metric_definitions,
)
from retail_analytics_agent.app import app
from retail_analytics_agent.database import get_database_connection
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.settings import Settings, get_settings


client = TestClient(app)


def _settings(*, public_demo_mode: bool = False) -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password=SecretStr("test_password"),
        public_demo_mode=public_demo_mode,
        _env_file=None,
    )


def _admin() -> AccessContext:
    return AccessContext(user_id="ADMIN-001", role=AccessRole.ADMIN)


def _analyst() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def test_metric_definition_view_uses_versioned_catalog() -> None:
    metrics = list_metric_definitions()

    sales = next(item for item in metrics if item.source_id == "metric.sales_amount.v1")
    assert sales.name == "销售额"
    assert sales.version == "v1"
    assert sales.formula == "SUM(order_items.quantity * order_items.unit_price)"
    assert sales.source_tables == ("orders", "order_items")


def test_admin_audit_query_returns_typed_entries() -> None:
    now = datetime.now(timezone.utc)
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "request_id": "REQ-001",
            "user_id": "USER-001",
            "access_role": "analyst",
            "original_question": "最近30天各渠道销售额",
            "status": "succeeded",
            "row_count": 4,
            "duration_ms": 1260.5,
            "max_rows": 10,
            "approval_required": False,
            "created_at": now,
            "updated_at": now,
        }
    ]

    result = list_admin_audit_entries(
        connection,
        status=AdminAuditStatus.SUCCEEDED,
        days=7,
        limit=20,
    )

    assert result[0].original_question == "最近30天各渠道销售额"
    assert result[0].status is AdminAuditStatus.SUCCEEDED
    params = connection.execute.call_args.args[1]
    assert params["status"] == "succeeded"
    assert params["days"] == 7
    assert params["limit"] == 20


def test_admin_audit_query_types_nullable_filters_for_postgres() -> None:
    assert "CAST(%(request_id)s AS text) IS NULL" in ADMIN_AUDIT_SELECT_SQL
    assert "CAST(%(user_id)s AS text) IS NULL" in ADMIN_AUDIT_SELECT_SQL
    assert "CAST(%(status)s AS text) IS NULL" in ADMIN_AUDIT_SELECT_SQL
    assert (
        "CAST(%(approval_required)s AS boolean) IS NULL"
        in ADMIN_AUDIT_SELECT_SQL
    )


def test_admin_can_read_metric_endpoint() -> None:
    app.dependency_overrides[get_access_context] = _admin
    app.dependency_overrides[get_settings] = _settings
    try:
        response = client.get("/admin/metrics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert any(item["name"] == "销售额" for item in response.json())


def test_analyst_cannot_read_admin_metric_endpoint() -> None:
    app.dependency_overrides[get_access_context] = _analyst
    app.dependency_overrides[get_settings] = _settings
    try:
        response = client.get("/admin/metrics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {"detail": "只有管理员可以查看这个页面。"}


def test_admin_audit_endpoint_uses_database_dependency() -> None:
    now = datetime.now(timezone.utc)
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "request_id": "REQ-002",
            "user_id": "ADMIN-001",
            "access_role": "admin",
            "original_question": "查看退款原因",
            "status": "approval_required",
            "row_count": None,
            "duration_ms": None,
            "max_rows": 10,
            "approval_required": True,
            "created_at": now,
            "updated_at": now,
        }
    ]
    app.dependency_overrides[get_access_context] = _admin
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_database_connection] = lambda: connection
    try:
        response = client.get(
            "/admin/audit?status=approval_required&days=30&limit=10"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["approval_required"] is True
