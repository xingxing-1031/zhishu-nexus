from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
import re
from time import monotonic
from typing import Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from retail_analytics_agent.access_control import denied_columns_for_role
from retail_analytics_agent.fault_injection import inject_fault
from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    DEFAULT_SCHEMA_CATALOG,
)
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisDimension,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisSort,
    RetrievalEvidence,
    SortDirection,
)
from retail_analytics_agent.resilience import (
    RetryPolicy,
    WorkflowDeadlineExceeded,
    bounded_timeout_seconds,
    wait_before_retry,
)
from retail_analytics_agent.tracing import (
    TraceStatus,
    record_execution_trace,
)


class ModelInvocationError(RuntimeError):
    """Stable error for unavailable or invalid model responses."""


class AnalysisPlanner(Protocol):
    def plan(self, question: str, *, max_rows: int) -> AnalysisPlan: ...


class SQLGenerator(Protocol):
    def generate(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        evidence: Sequence[RetrievalEvidence],
        access_role: AccessRole,
        validation_error: str | None = None,
    ) -> str: ...


class ResultSummarizer(Protocol):
    def summarize(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        rows: Sequence[dict[str, object]],
    ) -> str: ...


_DIMENSION_SQL_COLUMNS = {
    AnalysisDimension.CHANNEL: "orders.channel",
    AnalysisDimension.PRODUCT: "products.name",
    AnalysisDimension.CATEGORY: "products.category",
    AnalysisDimension.ORDER_STATUS: "orders.status",
    AnalysisDimension.REFUND_STATUS: "refunds.status",
}

_FILTER_SQL_COLUMNS = {
    AnalysisFilterField.CHANNEL: "orders.channel",
    AnalysisFilterField.ORDER_STATUS: "orders.status",
    AnalysisFilterField.PRODUCT_ID: "products.product_id",
    AnalysisFilterField.CATEGORY: "products.category",
    AnalysisFilterField.REFUND_STATUS: "refunds.status",
}


def _sql_generation_contract(
    plan: AnalysisPlan,
    evidence: Sequence[RetrievalEvidence],
) -> dict[str, object]:
    """Build deterministic SQL obligations from the validated plan and evidence."""

    evidence_ids = {item.source_id for item in evidence}
    metric_definitions = [
        DEFAULT_METRIC_CATALOG.get(metric) for metric in plan.metrics
    ]
    required_tables = sorted(
        item.removeprefix("schema.")
        for item in evidence_ids
        if item.startswith("schema.") and not item.startswith("schema.join.")
    )
    required_joins = [
        {
            "source_id": join.source_id,
            "on": (
                f"{join.left_table}.{join.left_column} = "
                f"{join.right_table}.{join.right_column}"
            ),
        }
        for join in DEFAULT_SCHEMA_CATALOG.joins
        if join.source_id in evidence_ids
    ]
    time_column = (
        "refunds.created_at"
        if all(
            "refunds" in definition.source_tables
            for definition in metric_definitions
        )
        else "orders.created_at"
    )
    required_predicates = [
        f"{_FILTER_SQL_COLUMNS[fixed_filter.field]} = '{fixed_filter.value}'"
        for definition in metric_definitions
        for fixed_filter in definition.fixed_filters
    ]
    required_group_by = [
        _dimension_sql_expression(dimension, metric_definitions)
        for dimension in plan.dimensions
    ]
    required_order_by = [
        f"{item.field.value} "
        f"{'DESC' if item.direction is SortDirection.DESCENDING else 'ASC'}"
        for item in plan.sort
    ]
    sorted_fields = {item.field.value for item in plan.sort}
    required_order_by.extend(
        f"{dimension.value} ASC"
        for dimension in plan.dimensions
        if dimension.value not in sorted_fields
    )
    return {
        "required_tables": required_tables,
        "required_joins": required_joins,
        "metric_outputs": [
            {
                "metric": definition.metric.value,
                "formula": definition.formula,
                "output_alias": definition.metric.value,
            }
            for definition in metric_definitions
        ],
        "dimension_outputs": [
            {
                "plan_field": dimension.value,
                "sql_expression": _dimension_sql_expression(
                    dimension, metric_definitions
                ),
                "output_alias": dimension.value,
                "must_be_grouped": True,
            }
            for dimension in plan.dimensions
        ],
        "required_filters": [
            {
                "field": item.field.value,
                "operator": item.operator.value,
                "value": item.value,
            }
            for item in [
                *(
                    fixed_filter
                    for definition in metric_definitions
                    for fixed_filter in definition.fixed_filters
                ),
                *plan.filters,
            ]
        ],
        "required_predicates": required_predicates,
        "required_group_by": required_group_by,
        "required_order_by": required_order_by,
        "required_group_by_clause": (
            "GROUP BY " + ", ".join(required_group_by)
            if required_group_by
            else None
        ),
        "required_order_by_clause": (
            "ORDER BY " + ", ".join(required_order_by)
            if required_order_by
            else None
        ),
        "time_range": (
            {
                "days": plan.time_range.days,
                "column": time_column,
                "predicate": (
                    f"{time_column} >= %(start_time)s AND "
                    f"{time_column} < %(end_time)s"
                ),
                "parameter_source": "trusted workflow reference_time",
            }
            if plan.time_range is not None
            else None
        ),
        "hard_rule": (
            "Every required table and approved join must appear in SQL; "
            "every metric and dimension must be selected with its exact "
            "output alias; every dimension must be in GROUP BY."
        ),
    }


def _dimension_sql_expression(
    dimension: AnalysisDimension,
    metric_definitions: Sequence[MetricDefinition],
) -> str:
    if dimension is AnalysisDimension.DAY:
        table = (
            "refunds"
            if all(
                "refunds" in definition.source_tables
                for definition in metric_definitions
            )
            else "orders"
        )
        return (
            f"({table}.created_at AT TIME ZONE 'Asia/Shanghai')"
            "::date::text"
        )
    return _DIMENSION_SQL_COLUMNS[dimension]


class _OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class _OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _OllamaMessage


class _GeneratedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1)


class _GeneratedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)


_NUMBER_PATTERN = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def _normalized_numbers(value: object) -> set[Decimal]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, dict):
        return {
            number
            for item in value.values()
            for number in _normalized_numbers(item)
        }
    if isinstance(value, (list, tuple)):
        return {
            number
            for item in value
            for number in _normalized_numbers(item)
        }
    if isinstance(value, (int, float, Decimal)):
        try:
            return {Decimal(str(value)).normalize()}
        except InvalidOperation:
            return set()
    if isinstance(value, str):
        numbers: set[Decimal] = set()
        for token in _NUMBER_PATTERN.findall(value):
            try:
                numbers.add(Decimal(token.replace(",", "")).normalize())
            except InvalidOperation:
                continue
        return numbers
    return set()


def _validate_summary_numbers(
    answer: str,
    *,
    question: str,
    plan: AnalysisPlan,
    rows: Sequence[dict[str, object]],
) -> None:
    allowed = _normalized_numbers(question)
    allowed.update(_normalized_numbers(plan.model_dump(mode="json")))
    allowed.update(_normalized_numbers(rows))
    allowed.add(Decimal(len(rows)))
    unsupported = _normalized_numbers(answer) - allowed
    if unsupported:
        rendered = ", ".join(str(item) for item in sorted(unsupported))
        raise ModelInvocationError(
            "Ollama summary contains numbers absent from verified inputs: "
            f"{rendered}"
        )


class _ModelFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: AnalysisFilterField
    operator: AnalysisFilterOperator
    values: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_equals_value(self) -> "_ModelFilter":
        if (
            self.operator is AnalysisFilterOperator.EQUALS
            and len(self.values) != 1
        ):
            raise ValueError("equals filter requires exactly one value")
        return self


class _ModelAnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_goal: str = Field(min_length=1, max_length=500)
    metrics: list[AnalysisMetric] = Field(min_length=1, max_length=5)
    dimensions: list[AnalysisDimension] = Field(default_factory=list, max_length=5)
    filters: list[_ModelFilter] = Field(default_factory=list, max_length=10)
    time_range_days: int = Field(ge=0, le=365)
    sort: list[AnalysisSort] = Field(default_factory=list, max_length=5)
    limit: int | None = Field(default=None, ge=1, le=1000)

    def to_analysis_plan(self, *, default_limit: int) -> AnalysisPlan:
        selected_fields = {
            item.value for item in [*self.metrics, *self.dimensions]
        }
        return AnalysisPlan(
            analysis_goal=self.analysis_goal,
            metrics=self.metrics,
            dimensions=self.dimensions,
            filters=[
                {
                    "field": item.field,
                    "operator": item.operator,
                    "value": (
                        item.values[0]
                        if item.operator is AnalysisFilterOperator.EQUALS
                        else item.values
                    ),
                }
                for item in self.filters
            ],
            time_range=(
                {"days": self.time_range_days}
                if self.time_range_days > 0
                else None
            ),
            sort=[
                item
                for item in self.sort
                if item.field.value in selected_fields
            ],
            limit=self.limit if self.limit is not None else default_limit,
        )


def _remove_redundant_fixed_filters(plan: AnalysisPlan) -> AnalysisPlan:
    definitions = [
        DEFAULT_METRIC_CATALOG.get(metric) for metric in plan.metrics
    ]
    shared_fixed_filters = [
        fixed_filter
        for fixed_filter in definitions[0].fixed_filters
        if all(
            fixed_filter in definition.fixed_filters
            for definition in definitions[1:]
        )
    ]
    if not shared_fixed_filters:
        return plan
    return plan.model_copy(
        update={
            "filters": [
                item
                for item in plan.filters
                if item not in shared_fixed_filters
            ]
        }
    )


def _explicit_metric_hints(question: str) -> tuple[AnalysisMetric, ...]:
    normalized = question.casefold()
    matches = tuple(
        definition.metric
        for definition in DEFAULT_METRIC_CATALOG.definitions
        if any(alias.casefold() in normalized for alias in definition.aliases)
    )
    if matches:
        return matches
    if (
        "平均" in normalized
        and "订单" in normalized
        and any(term in normalized for term in ("金额", "多少钱", "钱"))
    ):
        return (AnalysisMetric.AVERAGE_ORDER_VALUE,)
    if "订单" in normalized and "退款" not in normalized:
        return (AnalysisMetric.ORDER_COUNT,)
    if "渠道" in normalized:
        return (AnalysisMetric.SALES_AMOUNT,)
    return ()


def _explicit_dimension_hints(
    question: str,
) -> tuple[AnalysisDimension, ...]:
    normalized = question.casefold()
    dimensions: list[AnalysisDimension] = []
    if any(term in normalized for term in ("渠道", "channel")):
        dimensions.append(AnalysisDimension.CHANNEL)
    if any(term in normalized for term in ("品类", "类别", "category")):
        dimensions.append(AnalysisDimension.CATEGORY)
    product_breakdown = any(
        term in normalized
        for term in (
            "每种商品",
            "每个商品",
            "各商品",
            "按商品",
            "商品分别",
            "最高的两个商品",
            "最高的2个商品",
            "top product",
            "by product",
            "per product",
        )
    )
    if product_breakdown:
        dimensions.append(AnalysisDimension.PRODUCT)
    if "退款状态" in normalized or (
        "退款" in normalized
        and any(term in normalized for term in ("按状态", "不同状态"))
    ):
        dimensions.append(AnalysisDimension.REFUND_STATUS)
    if "订单状态" in normalized or (
        "订单" in normalized
        and "退款" not in normalized
        and any(term in normalized for term in ("按状态", "不同状态"))
    ):
        dimensions.append(AnalysisDimension.ORDER_STATUS)
    if any(term in normalized for term in ("每天", "每日", "按日", "day")):
        dimensions.append(AnalysisDimension.DAY)
    return tuple(dict.fromkeys(dimensions))


def _planner_contract(question: str) -> dict[str, object]:
    explicit_metrics = _explicit_metric_hints(question)
    return {
        "supported_metrics": [
            {
                "metric": definition.metric.value,
                "display_name": definition.display_name,
                "aliases": list(definition.aliases),
                "supported_dimensions": [
                    dimension.value
                    for dimension in definition.supported_dimensions
                ],
            }
            for definition in DEFAULT_METRIC_CATALOG.definitions
        ],
        "supported_dimensions": [
            dimension.value for dimension in AnalysisDimension
        ],
        "explicit_metric_hints": [
            metric.value for metric in explicit_metrics
        ],
        "hard_rule": (
            "When explicit_metric_hints is not empty, metrics must contain "
            "exactly those values and must not add unrequested metrics."
        ),
    }


def _align_explicit_metrics(
    plan: AnalysisPlan,
    *,
    question: str,
) -> AnalysisPlan:
    explicit_metrics = _explicit_metric_hints(question)
    if not explicit_metrics or tuple(plan.metrics) == explicit_metrics:
        return plan
    selected_fields = {
        item.value for item in [*explicit_metrics, *plan.dimensions]
    }
    return AnalysisPlan.model_validate(
        {
            **plan.model_dump(mode="json"),
            "metrics": [item.value for item in explicit_metrics],
            "sort": [
                item.model_dump(mode="json")
                for item in plan.sort
                if item.field.value in selected_fields
            ],
        }
    )


def _align_explicit_dimensions(
    plan: AnalysisPlan,
    *,
    question: str,
) -> AnalysisPlan:
    dimensions = _explicit_dimension_hints(question)
    aggregate_total = any(
        term in question for term in ("总共", "一共", "合计", "累计")
    )
    preserved_model_dimensions = (
        ()
        if plan.limit > 100 or aggregate_total or dimensions
        else tuple(
            dimension
            for dimension in plan.dimensions
            if dimension
            not in {
                AnalysisDimension.ORDER_STATUS,
                AnalysisDimension.REFUND_STATUS,
                AnalysisDimension.DAY,
            }
        )
    )
    aligned_dimensions = tuple(
        dict.fromkeys((*dimensions, *preserved_model_dimensions))
    )
    if tuple(plan.dimensions) == aligned_dimensions:
        return plan
    selected_fields = {
        item.value for item in [*plan.metrics, *aligned_dimensions]
    }
    return AnalysisPlan.model_validate(
        {
            **plan.model_dump(mode="json"),
            "dimensions": [item.value for item in aligned_dimensions],
            "sort": [
                item.model_dump(mode="json")
                for item in plan.sort
                if item.field.value in selected_fields
            ],
        }
    )


_KNOWN_CHANNEL_VALUES = ("淘宝", "京东", "抖音", "拼多多")


def _align_explicit_filters(
    plan: AnalysisPlan,
    *,
    question: str,
) -> AnalysisPlan:
    channel = next(
        (value for value in _KNOWN_CHANNEL_VALUES if value in question),
        None,
    )
    if channel is None:
        return plan
    filters = [
        item
        for item in plan.filters
        if item.field is not AnalysisFilterField.CHANNEL
    ]
    filters.append(
        {
            "field": AnalysisFilterField.CHANNEL,
            "operator": AnalysisFilterOperator.EQUALS,
            "value": channel,
        }
    )
    return AnalysisPlan.model_validate(
        {**plan.model_dump(mode="json"), "filters": filters}
    )


def _normalize_sort(plan: AnalysisPlan) -> AnalysisPlan:
    if plan.limit > 100 or not plan.dimensions:
        expected_sort: list[AnalysisSort] = []
    elif all(
        any(
            item.field.value == dimension.value
            and item.operator is AnalysisFilterOperator.EQUALS
            for item in plan.filters
        )
        for dimension in plan.dimensions
    ):
        expected_sort = []
    elif AnalysisDimension.DAY in plan.dimensions:
        expected_sort = [
            AnalysisSort(
                field=AnalysisDimension.DAY,
                direction=SortDirection.ASCENDING,
            )
        ]
    else:
        expected_sort = [
            AnalysisSort(
                field=plan.metrics[0],
                direction=SortDirection.DESCENDING,
            )
        ]
    if plan.sort == expected_sort:
        return plan
    return plan.model_copy(update={"sort": expected_sort})


_PLACEHOLDER_FILTER_VALUES = {
    "*",
    "all",
    "any",
    "全部",
    "所有",
    "任意",
}


def _remove_placeholder_filters(plan: AnalysisPlan) -> AnalysisPlan:
    def is_placeholder(value: object) -> bool:
        return isinstance(value, str) and value.casefold() in (
            _PLACEHOLDER_FILTER_VALUES
        )

    filters = [
        item
        for item in plan.filters
        if not (
            is_placeholder(item.value)
            or (
                isinstance(item.value, list)
                and any(is_placeholder(value) for value in item.value)
            )
        )
    ]
    if len(filters) == len(plan.filters):
        return plan
    return plan.model_copy(update={"filters": filters})


_EXPLICIT_RESULT_LIMIT = re.compile(
    r"(?:\b(?:top|limit)\s*\d+\b|\d+\s*(?:行|条|个|项|件|商品|订单))",
    re.IGNORECASE,
)


def _apply_default_limit_when_unrequested(
    plan: AnalysisPlan,
    *,
    question: str,
    max_rows: int,
    default_limit: int,
) -> AnalysisPlan:
    if (
        plan.limit == max_rows
        and max_rows > default_limit
        and not _EXPLICIT_RESULT_LIMIT.search(question)
    ):
        return plan.model_copy(update={"limit": default_limit})
    return plan


def _planner_response_schema(max_rows: int) -> dict[str, object]:
    metric_values = [item.value for item in AnalysisMetric]
    dimension_values = [item.value for item in AnalysisDimension]
    filter_field_values = [item.value for item in AnalysisFilterField]
    filter_operator_values = [item.value for item in AnalysisFilterOperator]
    direction_values = [item.value for item in SortDirection]
    return {
        "type": "object",
        "properties": {
            "analysis_goal": {"type": "string"},
            "metrics": {
                "type": "array",
                "items": {"type": "string", "enum": metric_values},
                "minItems": 1,
                "maxItems": 5,
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": dimension_values},
                "maxItems": 5,
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": filter_field_values,
                        },
                        "operator": {
                            "type": "string",
                            "enum": filter_operator_values,
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                    "required": ["field", "operator", "values"],
                    "additionalProperties": False,
                },
                "maxItems": 10,
            },
            "time_range_days": {
                "type": "integer",
                "minimum": 0,
                "maximum": 365,
            },
            "sort": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": [*metric_values, *dimension_values],
                        },
                        "direction": {
                            "type": "string",
                            "enum": direction_values,
                        },
                    },
                    "required": ["field", "direction"],
                    "additionalProperties": False,
                },
                "maxItems": 5,
            },
            "limit": {
                "description": (
                    "Result count explicitly requested in the user's question; "
                    "null when the user did not request a count."
                ),
                "anyOf": [
                    {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": max_rows,
                    },
                    {"type": "null"},
                ],
            },
        },
        "required": [
            "analysis_goal",
            "metrics",
            "dimensions",
            "filters",
            "time_range_days",
            "sort",
            "limit",
        ],
        "additionalProperties": False,
    }


def _chat_json(
    client: httpx.Client,
    *,
    model: str,
    system_prompt: str,
    user_payload: dict[str, object],
    response_schema: dict[str, object] | str,
    timeout_seconds: float,
    retry_policy: RetryPolicy,
    component: str,
) -> str:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": response_schema,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
    }
    last_error: ModelInvocationError | None = None

    for attempt in range(1, retry_policy.max_attempts + 1):
        record_execution_trace(
            component,
            TraceStatus.STARTED,
            attempt=attempt,
        )
        started_at = monotonic()
        try:
            inject_fault(component)
            response = client.post(
                "/api/chat",
                json=payload,
                timeout=bounded_timeout_seconds(timeout_seconds),
            )
            response.raise_for_status()
            content = _OllamaChatResponse.model_validate(
                response.json()
            ).message.content
            record_execution_trace(
                component,
                TraceStatus.SUCCEEDED,
                attempt=attempt,
                duration_ms=int((monotonic() - started_at) * 1000),
            )
            return content
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            last_error = ModelInvocationError(
                "Ollama model invocation failed: "
                f"HTTP {exc.response.status_code}: {detail}"
            )
            retryable = exc.response.status_code in {
                408,
                429,
                500,
                502,
                503,
                504,
            }
            error_type = f"HTTP_{exc.response.status_code}"
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = ModelInvocationError(
                f"Ollama model invocation failed: {exc}"
            )
            retryable = True
            error_type = type(exc).__name__
        except WorkflowDeadlineExceeded as exc:
            record_execution_trace(
                component,
                TraceStatus.FAILED,
                attempt=attempt,
                duration_ms=int((monotonic() - started_at) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise ModelInvocationError(str(exc)) from exc
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            record_execution_trace(
                component,
                TraceStatus.FAILED,
                attempt=attempt,
                duration_ms=int((monotonic() - started_at) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise ModelInvocationError(
                f"Ollama model invocation failed: {exc}"
            ) from exc

        assert last_error is not None
        record_execution_trace(
            component,
            TraceStatus.FAILED,
            attempt=attempt,
            duration_ms=int((monotonic() - started_at) * 1000),
            error_type=error_type,
            error_message=str(last_error),
        )
        if not retryable or attempt >= retry_policy.max_attempts:
            raise last_error
        delay = retry_policy.delay_before_attempt(attempt + 1)
        record_execution_trace(
            component,
            TraceStatus.RETRY_SCHEDULED,
            attempt=attempt,
            error_type=error_type,
            error_message=str(last_error),
            retry_delay_ms=int(delay * 1000),
        )
        try:
            wait_before_retry(delay)
        except WorkflowDeadlineExceeded as exc:
            raise ModelInvocationError(str(exc)) from exc

    raise AssertionError("model retry loop exited unexpectedly")


@dataclass(frozen=True, slots=True)
class OllamaAnalysisPlanner:
    client: httpx.Client
    model: str = "qwen3:4b"
    timeout_seconds: float = 120
    retry_policy: RetryPolicy = RetryPolicy()

    def plan(self, question: str, *, max_rows: int) -> AnalysisPlan:
        if not question.strip():
            raise ValueError("question must not be empty")
        if max_rows < 1:
            raise ValueError("max_rows must be positive")

        default_limit = min(100, max_rows)
        content = _chat_json(
            self.client,
            model=self.model,
            system_prompt=(
                "你是零售分析规划器。把用户问题转换为给定 JSON Schema，"
                "只能使用 Schema 中允许的指标、维度、筛选和排序字段。"
                "计划只表达用户意图，不猜测 SQL、表、字段或 JOIN。"
                "用户没有明确筛选条件时 filters 必须为空；指标固定业务规则会由检索证据补充。"
                "时间范围只能写入 time_range_days，不能写成 filter；没有时间范围时填 0。"
            ),
            user_payload={
                "question": question,
                "max_rows": max_rows,
                "default_limit": default_limit,
                "planner_contract": _planner_contract(question),
                "planning_rules": [
                    "Only add a dimension for an explicit grouping, comparison, or breakdown request.",
                    "A status used only as a condition must not become a dimension.",
                    "Paid-order filtering for sales_amount, order_count, units_sold, and average_order_value is supplied by fixed metric evidence; do not duplicate order_status=paid in filters.",
                    "Set limit to null unless the question explicitly requests a result count; the application will then apply default_limit.",
                ],
            },
            response_schema=_planner_response_schema(max_rows),
            timeout_seconds=self.timeout_seconds,
            retry_policy=self.retry_policy,
            component="model.plan",
        )
        try:
            plan = _ModelAnalysisPlan.model_validate_json(
                content
            ).to_analysis_plan(default_limit=default_limit)
        except (ValidationError, ValueError) as exc:
            raise ModelInvocationError(
                f"Ollama planner returned an invalid analysis plan: {exc}"
            ) from exc
        if plan.limit > max_rows:
            raise ModelInvocationError(
                "Ollama planner returned a limit greater than max_rows"
            )
        plan = _apply_default_limit_when_unrequested(
            plan,
            question=question,
            max_rows=max_rows,
            default_limit=default_limit,
        )
        plan = _align_explicit_metrics(plan, question=question)
        plan = _align_explicit_dimensions(plan, question=question)
        plan = _align_explicit_filters(plan, question=question)
        plan = _normalize_sort(plan)
        plan = _remove_placeholder_filters(plan)
        return _remove_redundant_fixed_filters(plan)


@dataclass(frozen=True, slots=True)
class OllamaSQLGenerator:
    client: httpx.Client
    model: str = "qwen3:4b"
    timeout_seconds: float = 120
    retry_policy: RetryPolicy = RetryPolicy()

    def generate(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        evidence: Sequence[RetrievalEvidence],
        access_role: AccessRole,
        validation_error: str | None = None,
    ) -> str:
        if not evidence:
            raise ValueError("retrieval evidence is required for SQL generation")

        content = _chat_json(
            self.client,
            model=self.model,
            system_prompt=(
                "你是 PostgreSQL 只读 SQL 生成器。只输出一条 SELECT 或 WITH 查询。"
                "必须严格使用分析计划表达本次意图，并严格使用检索证据中的公式、"
                "固定筛选、表、字段和批准的 JOIN。禁止 SELECT *，禁止写操作，"
                "禁止使用证据中没有出现的表、字段和关系。若提供了上一次安全校验错误，"
                "必须修正该错误。SELECT 输出中的指标和维度必须使用分析计划枚举值作为别名，"
                "例如 channel 和 sales_amount，供后续图表规格安全引用。"
                "sql_generation_contract 是强制执行清单，其中每张表、每条 JOIN、"
                "每个输出别名、固定筛选、时间参数和分组要求都必须出现在 SQL 中。"
                "请直接复制 contract.required_predicates、contract.required_group_by "
                "和 contract.time_range.predicate 的文本；不要自行改写时间条件。"
                "required_group_by_clause 和 required_order_by_clause 非空时，"
                "必须把完整子句原样加入 SQL。"
                "禁止用 NOW() 或 CURRENT_TIMESTAMP 代替 start_time/end_time。不要解释 SQL。"
            ),
            user_payload={
                "question": question,
                "analysis_plan": plan.model_dump(mode="json"),
                "retrieval_evidence": [
                    item.model_dump(mode="json") for item in evidence
                ],
                "sql_generation_contract": _sql_generation_contract(
                    plan,
                    evidence,
                ),
                "access_role": access_role.value,
                "forbidden_columns": [
                    f"{table}.{column}"
                    for table, column in sorted(
                        denied_columns_for_role(access_role)
                    )
                ],
                "previous_validation_error": validation_error,
            },
            response_schema=_GeneratedSQL.model_json_schema(),
            timeout_seconds=self.timeout_seconds,
            retry_policy=self.retry_policy,
            component="model.generate_sql",
        )
        try:
            sql = _GeneratedSQL.model_validate_json(content).sql.strip()
        except (ValidationError, ValueError) as exc:
            raise ModelInvocationError(
                f"Ollama SQL generator returned invalid output: {exc}"
            ) from exc
        if not sql:
            raise ModelInvocationError("Ollama SQL generator returned empty SQL")
        return sql


@dataclass(frozen=True, slots=True)
class OllamaResultSummarizer:
    client: httpx.Client
    model: str = "qwen3:4b"
    timeout_seconds: float = 120
    retry_policy: RetryPolicy = RetryPolicy()

    def summarize(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        rows: Sequence[dict[str, object]],
    ) -> str:
        content = _chat_json(
            self.client,
            model=self.model,
            system_prompt=(
                "你是零售分析结果解释器。只能根据给定查询结果回答，"
                "不得补造结果中不存在的数字或原因。结果为空时明确说明没有符合条件的数据。"
                "回答要简洁，并保留重要数值和分组名称。"
            ),
            user_payload={
                "question": question,
                "analysis_plan": plan.model_dump(mode="json"),
                "query_rows": list(rows),
            },
            response_schema=_GeneratedSummary.model_json_schema(),
            timeout_seconds=self.timeout_seconds,
            retry_policy=self.retry_policy,
            component="model.summarize",
        )
        try:
            answer = _GeneratedSummary.model_validate_json(content).answer.strip()
        except (ValidationError, ValueError) as exc:
            raise ModelInvocationError(
                f"Ollama summarizer returned invalid output: {exc}"
            ) from exc
        if not answer:
            raise ModelInvocationError("Ollama summarizer returned an empty answer")
        _validate_summary_numbers(
            answer,
            question=question,
            plan=plan,
            rows=rows,
        )
        return answer
