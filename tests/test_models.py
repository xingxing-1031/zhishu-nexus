from decimal import Decimal

import pytest
from pydantic import ValidationError

from retail_analytics_agent.models import (
    AnalysisRequest,
    Order,
    OrderStatus,
    Product,
    Refund,
    RefundStatus,
)


def test_order_accepts_valid_data() -> None:
    order = Order(
        order_id="ORD-001",
        channel="taobao",
        amount="99.90",
        status="paid",
    )

    assert order.order_id == "ORD-001"
    assert order.channel == "taobao"
    assert order.amount == Decimal("99.90")
    assert order.status is OrderStatus.PAID

    
def test_order_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        Order(
            order_id="ORD-002",
            channel="jd",
            amount="-0.01",
            status="paid",
        )


def test_order_accepts_zero_amount() -> None:
    order = Order(
        order_id="ORD-003",
        channel="douyin",
        amount="0",
        status="paid",
    )

    assert order.amount == Decimal("0")


def test_order_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Order(
            order_id="ORD-004",
            channel="taobao",
            amount="19.90",
            status="unknown",
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("status",)
    assert error["input"] == "unknown"


def test_product_accepts_valid_data() -> None:
    product=Product(
        product_id="001",
        name="phone",
        category="phones",
        unit_price="1000",
    )

    assert product.product_id == "001"
    assert product.name == "phone"
    assert product.category == "phones"
    assert product.unit_price == Decimal("1000")


def test_product_rejects_negative_unit_price()-> None:
    with pytest.raises(ValidationError):
        Product(
            product_id="001",
            name="phone",
            category="phones",
            unit_price="-1000",
        )


def test_refund_accepts_valid_data()-> None:
    refund=Refund(
        refund_id="001",
        order_id="001",
        refund_amount="1",
        reason="不想要了",
        status="requested",
    )

    assert refund.refund_id == "001"
    assert refund.refund_amount == Decimal("1")
    assert refund.status is RefundStatus.REQUESTED


def test_refund_rejects_zero_amount()-> None:
    with pytest.raises(ValidationError):
        Refund(
            refund_id="001",
            order_id="001",
            refund_amount="0",
            reason="不想要了",
            status="requested"
        )


def test_analysis_request_uses_default_max_rows() -> None:
    request = AnalysisRequest(
        request_id="REQ-001",
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
    )

    assert request.max_rows == 100


def test_analysis_request_rejects_too_many_rows() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(
            request_id="REQ-002",
            user_id="USER-001",
            question="查询全部订单",
            max_rows=1001,
        )


def test_analysis_request_rejects_zero_rows() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(
            request_id="REQ-002",
            user_id="USER-001",
            question="查询全部订单",
            max_rows=0,
        )
