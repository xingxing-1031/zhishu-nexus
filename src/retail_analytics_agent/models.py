from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Order(BaseModel):
    order_id: str
    channel: str
    amount: Decimal = Field(ge=0)
    status: OrderStatus


class Product(BaseModel):
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    unit_price: Decimal = Field(ge=0)


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class Refund(BaseModel):
    refund_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    refund_amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=1)
    status: RefundStatus


class AnalysisRequest(BaseModel):
    request_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    max_rows: int = Field(default=100, ge=1, le=1000)


class ChannelSalesSummary(BaseModel):
    channel: str = Field(min_length=1)
    paid_order_count: int = Field(ge=0)
    sales_amount: Decimal = Field(ge=0)


class ProductSalesSummary(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    units_sold: int = Field(ge=0)
    sales_amount: Decimal = Field(ge=0)


class RefundStatusSummary(BaseModel):
    status: RefundStatus
    refund_count: int = Field(ge=0)
    refund_amount: Decimal = Field(ge=0)


class OrderStatusSummary(BaseModel):
    status: OrderStatus
    order_count: int = Field(ge=0)
    order_amount: Decimal = Field(ge=0)
