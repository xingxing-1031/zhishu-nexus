from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.dataset_mapping import (
    _role_compatible,
    DatasetMapping,
    MappingField,
    MappingRole,
)
from retail_analytics_agent.dataset_models import SchemaProfile


class MetricStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    ARCHIVED = "archived"


class MetricValidationError(ValueError):
    """Raised when dataset metrics cannot be derived from the current data."""


class DatasetMetric(BaseModel):
    """Versioned dataset-level metric definition confirmed by an administrator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=80)
    dataset_version: int = Field(ge=1)
    metric_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    metric_version: str = Field(default="v1", pattern=r"^v[1-9][0-9]*$")
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=500)
    aggregation: str = Field(min_length=1, max_length=40)
    formula: str = Field(min_length=1, max_length=300)
    source_role: MappingRole
    source_table: str = Field(min_length=1, max_length=63)
    source_column: str = Field(min_length=1, max_length=63)
    supported_dimensions: tuple[MappingRole, ...] = ()
    fixed_filters: tuple[str, ...] = ()
    status: MetricStatus = MetricStatus.PROPOSED
    effective_from: datetime | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_unique_dimensions(self) -> "DatasetMetric":
        if len(set(self.supported_dimensions)) != len(self.supported_dimensions):
            raise ValueError("supported_dimensions must not contain duplicates")
        return self

    @property
    def source_id(self) -> str:
        return (
            f"metric.{self.dataset_id}.v{self.dataset_version}"
            f".{self.metric_id}.{self.metric_version}"
        )


_AGG_SUM = "SUM"
_AGG_COUNT_DISTINCT = "COUNT_DISTINCT"
_AGG_RATIO = "RATIO"

_SALES_DIMENSIONS = (
    MappingRole.CHANNEL,
    MappingRole.REGION,
    MappingRole.CATEGORY,
)


def propose_metrics(
    dataset_id: str,
    dataset_version: int,
    mapping: DatasetMapping,
    profile: SchemaProfile,
) -> tuple[DatasetMetric, ...]:
    """Derive provable sales metrics from confirmed field roles.

    Only metrics whose source fields exist in the confirmed mapping are
    proposed. Metrics that require additional state or a customer definition
    (e.g. refund rate, repeat purchase rate) are never auto-published.
    """
    role_sources = {field.role: field for field in mapping.fields}
    amount = role_sources.get(MappingRole.AMOUNT)
    order_id = role_sources.get(MappingRole.ORDER_ID)
    quantity = role_sources.get(MappingRole.QUANTITY)
    dimensions = tuple(role for role in _SALES_DIMENSIONS if role in role_sources)

    metrics: list[DatasetMetric] = []
    if amount is not None:
        metrics.append(
            _metric(
                dataset_id,
                dataset_version,
                metric_id="sales_amount",
                name="销售额",
                definition="销售额为已确认金额字段的合计。",
                aggregation=_AGG_SUM,
                formula=f"SUM({amount.table}.{amount.column})",
                field=amount,
                dimensions=dimensions,
            )
        )
        if order_id is not None:
            metrics.append(
                _metric(
                    dataset_id,
                    dataset_version,
                    metric_id="avg_order_value",
                    name="客单价",
                    definition="客单价为销售额与去重订单数的比值。",
                    aggregation=_AGG_RATIO,
                    formula=(
                        f"SUM({amount.table}.{amount.column}) "
                        f"/ COUNT(DISTINCT {order_id.table}.{order_id.column})"
                    ),
                    field=amount,
                    dimensions=dimensions,
                )
            )
    if order_id is not None:
        metrics.append(
            _metric(
                dataset_id,
                dataset_version,
                metric_id="order_count",
                name="订单数",
                definition="订单数按唯一订单标识去重统计。",
                aggregation=_AGG_COUNT_DISTINCT,
                formula=f"COUNT(DISTINCT {order_id.table}.{order_id.column})",
                field=order_id,
                dimensions=(),
            )
        )
    if quantity is not None:
        metrics.append(
            _metric(
                dataset_id,
                dataset_version,
                metric_id="units_sold",
                name="销量",
                definition="销量为已确认数量字段的合计。",
                aggregation=_AGG_SUM,
                formula=f"SUM({quantity.table}.{quantity.column})",
                field=quantity,
                dimensions=dimensions,
            )
        )
    return tuple(metrics)


def _metric(
    dataset_id: str,
    dataset_version: int,
    *,
    metric_id: str,
    name: str,
    definition: str,
    aggregation: str,
    formula: str,
    field: MappingField,
    dimensions: tuple[MappingRole, ...],
) -> DatasetMetric:
    return DatasetMetric(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        metric_id=metric_id,
        metric_version="v1",
        name=name,
        definition=definition,
        aggregation=aggregation,
        formula=formula,
        source_role=field.role,
        source_table=field.table,
        source_column=field.column,
        supported_dimensions=dimensions,
    )


def validate_metrics(
    metrics: tuple[DatasetMetric, ...],
    mapping: DatasetMapping,
    profile: SchemaProfile,
) -> tuple[DatasetMetric, ...]:
    """Ensure every metric references only confirmed, type-compatible fields."""
    role_sources = {field.role: field for field in mapping.fields}
    tables = {table.table_name: table for table in profile.tables}
    seen_ids: set[str] = set()
    for metric in metrics:
        field = role_sources.get(metric.source_role)
        if field is None:
            raise MetricValidationError(
                "metric source role is not confirmed in mapping: "
                f"{metric.source_role.value}"
            )
        if (field.table, field.column) != (metric.source_table, metric.source_column):
            raise MetricValidationError(
                "metric source column must match the confirmed mapping: "
                f"{metric.source_column}"
            )
        table = tables.get(metric.source_table)
        if table is None:
            raise MetricValidationError(
                f"metric table does not exist: {metric.source_table}"
            )
        column = next(
            (item for item in table.columns if item.name == metric.source_column),
            None,
        )
        if column is None:
            raise MetricValidationError(
                f"metric column does not exist: {metric.source_column}"
            )
        if not _role_compatible(
            metric.source_role,
            column.normalized_type,
            column.candidate_roles,
        ):
            raise MetricValidationError(
                "metric column is not type compatible: "
                f"{metric.source_role.value} -> {metric.source_column}"
            )
        for dimension in metric.supported_dimensions:
            if dimension not in role_sources:
                raise MetricValidationError(
                    "metric dimension is not confirmed in mapping: "
                    f"{dimension.value}"
                )
        if metric.metric_id in seen_ids:
            raise MetricValidationError(f"duplicate metric_id: {metric.metric_id}")
        seen_ids.add(metric.metric_id)
    return metrics


def metric_version_number(version: str) -> int:
    return int(version[1:])


def with_latest_version(
    metric: DatasetMetric,
    existing: tuple[DatasetMetric, ...],
) -> DatasetMetric:
    """Keep metric versions append-only: new definitions get a new version."""
    versions = [
        metric_version_number(item.metric_version)
        for item in existing
        if item.metric_id == metric.metric_id
    ]
    if not versions:
        return metric
    return metric.model_copy(
        update={"metric_version": f"v{max(versions) + 1}"}
    )


def as_confirmed(metric: DatasetMetric, confirmed_by: str) -> DatasetMetric:
    now = datetime.now(UTC)
    return metric.model_copy(
        update={
            "status": MetricStatus.CONFIRMED,
            "confirmed_by": confirmed_by,
            "confirmed_at": now,
            "effective_from": now,
        }
    )


def has_confirmed_metric(metrics: tuple[DatasetMetric, ...]) -> bool:
    return any(item.status is MetricStatus.CONFIRMED for item in metrics)
