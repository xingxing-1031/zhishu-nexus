from decimal import Decimal
from unittest.mock import Mock

import pytest

from retail_analytics_agent.queries import (
    CHANNEL_SALES_SQL,
    ORDER_STATUS_SQL,
    PRODUCT_SALES_SQL,
    REFUND_STATUS_SQL,
    get_channel_sales_summary,
    get_order_status_summary,
    get_product_sales_summary,
    get_refund_status_summary,
)


def test_get_channel_sales_summary_maps_rows_and_passes_days() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "channel": "京东",
            "paid_order_count": 2,
            "sales_amount": Decimal("11300.00"),
        }
    ]

    result = get_channel_sales_summary(connection, days=30)

    connection.execute.assert_called_once_with(
        CHANNEL_SALES_SQL,
        {"days": 30},
    )

    assert result[0].channel == "京东"
    assert result[0].paid_order_count == 2
    assert result[0].sales_amount == Decimal("11300.00")


@pytest.mark.parametrize("days", [0, 366])
def test_get_channel_sales_summary_rejects_invalid_days(days: int) -> None:
    connection = Mock()

    with pytest.raises(
        ValueError,
        match="days must be between 1 and 365",
    ):
        get_channel_sales_summary(connection, days=days)

    connection.execute.assert_not_called()


def test_get_product_sales_summary_maps_rows_and_passes_parameters() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "product_id": "PROD-001",
            "product_name": "Smartphone",
            "units_sold": 2,
            "sales_amount": Decimal("14000.00"),
        }
    ]

    result = get_product_sales_summary(
        connection,
        days=30,
        limit=10,
    )

    connection.execute.assert_called_once_with(
        PRODUCT_SALES_SQL,
        {
            "days": 30,
            "limit": 10,
        },
    )

    assert result[0].product_id == "PROD-001"
    assert result[0].product_name == "Smartphone"
    assert result[0].units_sold == 2
    assert result[0].sales_amount == Decimal("14000.00")


@pytest.mark.parametrize("days", [0, 366])
def test_get_product_sales_summary_rejects_invalid_days(days: int) -> None:
    connection = Mock()

    with pytest.raises(
        ValueError,
        match="days must be between 1 and 365",
    ):
        get_product_sales_summary(connection, days=days, limit=10)

    connection.execute.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101])
def test_get_product_sales_summary_rejects_invalid_limit(limit: int) -> None:
    connection = Mock()

    with pytest.raises(
        ValueError,
        match="limit must be between 1 and 100",
    ):
        get_product_sales_summary(connection, days=30, limit=limit)

    connection.execute.assert_not_called()


def test_get_refund_status_summary_maps_rows_and_passes_days() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "status": "completed",
            "refund_count": 2,
            "refund_amount": Decimal("1500.00"),
        }
    ]

    result = get_refund_status_summary(connection, days=30)

    connection.execute.assert_called_once_with(
        REFUND_STATUS_SQL,
        {"days": 30},
    )

    assert result[0].status.value == "completed"
    assert result[0].refund_count == 2
    assert result[0].refund_amount == Decimal("1500.00")


@pytest.mark.parametrize("days", [0, 366])
def test_get_refund_status_summary_rejects_invalid_days(days: int) -> None:
    connection = Mock()

    with pytest.raises(
        ValueError,
        match="days must be between 1 and 365",
    ):
        get_refund_status_summary(connection, days=days)

    connection.execute.assert_not_called()


def test_get_order_status_summary_maps_rows_and_passes_days() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "status": "paid",
            "order_count": 4,
            "order_amount": Decimal("20900.00"),
        }
    ]

    result = get_order_status_summary(connection, days=30)

    connection.execute.assert_called_once_with(
        ORDER_STATUS_SQL,
        {"days": 30},
    )

    assert result[0].status.value == "paid"
    assert result[0].order_count == 4
    assert result[0].order_amount == Decimal("20900.00")


@pytest.mark.parametrize("days", [0, 366])
def test_get_order_status_summary_rejects_invalid_days(days: int) -> None:
    connection = Mock()

    with pytest.raises(
        ValueError,
        match="days must be between 1 and 365",
    ):
        get_order_status_summary(connection, days=days)

    connection.execute.assert_not_called()
