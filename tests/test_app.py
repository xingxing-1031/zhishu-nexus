from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from retail_analytics_agent.app import app
from retail_analytics_agent.database import get_database_connection


client = TestClient(app)


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
