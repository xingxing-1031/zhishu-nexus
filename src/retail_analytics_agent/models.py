from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class AccessRole(StrEnum):
    ANALYST = "analyst"
    ADMIN = "admin"


class AccessContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1)
    role: AccessRole


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class AnalysisResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    RUNNING = "running"


class QueryRisk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_approval: bool
    reasons: tuple[str, ...] = ()
    sensitive_columns: tuple[str, ...] = ()
    result_limit: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def validate_approval_reasons(self) -> Self:
        if self.requires_approval != bool(self.reasons):
            raise ValueError(
                "approval reasons must match requires_approval"
            )
        return self


class ApprovalResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> Self:
        if self.decision is ApprovalDecision.REJECT:
            if self.reason is None or not self.reason.strip():
                raise ValueError("rejection reason is required")
        return self


class ApprovalRequiredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    status: ApprovalStatus = ApprovalStatus.PENDING
    access_role: AccessRole
    sql: str = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    sensitive_columns: tuple[str, ...] = ()
    result_limit: int = Field(ge=1, le=1000)
    trace: tuple[str, ...]


class ApprovalRejectedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    status: ApprovalStatus = ApprovalStatus.REJECTED
    reviewed_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    trace: tuple[str, ...]


class AnalysisRejectedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    status: Literal["rejected"] = "rejected"
    access_role: AccessRole
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    trace: tuple[str, ...]


class AssistantResponseStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"


class AssistantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    status: AssistantResponseStatus
    access_role: AccessRole
    reason_code: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    trace: tuple[str, ...]


class AnalysisMetric(StrEnum):
    SALES_AMOUNT = "sales_amount"
    ORDER_COUNT = "order_count"
    UNITS_SOLD = "units_sold"
    REFUND_AMOUNT = "refund_amount"
    REFUND_COUNT = "refund_count"
    AVERAGE_ORDER_VALUE = "average_order_value"


class AnalysisDimension(StrEnum):
    CHANNEL = "channel"
    PRODUCT = "product"
    CATEGORY = "category"
    ORDER_STATUS = "order_status"
    REFUND_STATUS = "refund_status"
    DAY = "day"


class AnalysisFilterField(StrEnum):
    CHANNEL = "channel"
    ORDER_STATUS = "order_status"
    PRODUCT_ID = "product_id"
    CATEGORY = "category"
    REFUND_STATUS = "refund_status"


class AnalysisFilterOperator(StrEnum):
    EQUALS = "equals"
    IN = "in"


class SortDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class _StrictPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PlanFilterValue = str | int | Decimal | bool


class AnalysisFilter(_StrictPlanModel):
    field: AnalysisFilterField
    operator: AnalysisFilterOperator = AnalysisFilterOperator.EQUALS
    value: PlanFilterValue | list[PlanFilterValue]

    @model_validator(mode="after")
    def validate_operator_value(self) -> Self:
        value_is_list = isinstance(self.value, list)
        if self.operator is AnalysisFilterOperator.IN:
            if not value_is_list or not self.value:
                raise ValueError("in operator requires a non-empty list value")
        elif value_is_list:
            raise ValueError("equals operator requires a scalar value")
        return self


class RelativeTimeRange(_StrictPlanModel):
    days: int = Field(ge=1, le=365)


class AnalysisSort(_StrictPlanModel):
    field: AnalysisMetric | AnalysisDimension
    direction: SortDirection = SortDirection.DESCENDING


class AnalysisPlan(_StrictPlanModel):
    analysis_goal: str = Field(min_length=1, max_length=500)
    metrics: list[AnalysisMetric] = Field(min_length=1, max_length=5)
    dimensions: list[AnalysisDimension] = Field(default_factory=list, max_length=5)
    filters: list[AnalysisFilter] = Field(default_factory=list, max_length=10)
    time_range: RelativeTimeRange | None = None
    sort: list[AnalysisSort] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_selected_fields(self) -> Self:
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must not contain duplicates")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensions must not contain duplicates")

        selected_fields = {
            item.value for item in [*self.metrics, *self.dimensions]
        }
        invalid_sort_fields = [
            item.field.value
            for item in self.sort
            if item.field.value not in selected_fields
        ]
        if invalid_sort_fields:
            raise ValueError(
                "sort fields must be selected metrics or dimensions: "
                + ", ".join(invalid_sort_fields)
            )
        return self


class RetrievalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    KPI = "kpi"


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chart_type: ChartType
    title: str = Field(min_length=1)
    x_field: str | None = None
    y_fields: tuple[str, ...] = Field(min_length=1)


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    status: AnalysisResultStatus = AnalysisResultStatus.SUCCEEDED
    access_role: AccessRole
    answer: str = Field(min_length=1)
    plan: AnalysisPlan
    rows: list[dict[str, Any]]
    chart_spec: ChartSpec | None
    evidence_source_ids: tuple[str, ...]
    retry_count: int = Field(ge=0)
    degradation_reason: str | None = None
    trace: tuple[str, ...]

    @model_validator(mode="after")
    def validate_degradation(self) -> Self:
        if self.status is AnalysisResultStatus.DEGRADED:
            if self.degradation_reason is None:
                raise ValueError("degraded result requires a reason")
        elif self.degradation_reason is not None:
            raise ValueError(
                "successful result must not have a degradation reason"
            )
        return self


class AnalysisRunningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    status: AnalysisResultStatus = AnalysisResultStatus.RUNNING
    access_role: AccessRole
    trace: tuple[str, ...] = ()


AnalysisOutcome = (
    AnalysisResponse
    | AnalysisRunningResponse
    | AnalysisRejectedResponse
    | AssistantResponse
    | ApprovalRequiredResponse
    | ApprovalRejectedResponse
)


class AnalysisEventType(StrEnum):
    STATUS = "status"
    RESULT = "result"
    ERROR = "error"
    APPROVAL_REQUIRED = "approval_required"
    REJECTED = "rejected"
    ASSISTANT_MESSAGE = "assistant_message"


class AnalysisStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: AnalysisEventType
    node: str | None = None
    message: str = Field(min_length=1)
    response: AnalysisResponse | None = None
    assistant: AssistantResponse | None = None
    approval: ApprovalRequiredResponse | None = None
    rejection: AnalysisRejectedResponse | ApprovalRejectedResponse | None = None


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
