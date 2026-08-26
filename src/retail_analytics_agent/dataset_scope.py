from __future__ import annotations

from typing import Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp, parse_one

from retail_analytics_agent.dataset_mapping import (
    DatasetMapping,
    MappingField,
    MappingRole,
)
from retail_analytics_agent.dataset_models import (
    DatasetRecord,
    DatasetStatus,
    SchemaProfile,
    TableProfile,
)
from retail_analytics_agent.knowledge import (
    MetricCatalog,
    MetricDefinition,
    SchemaCatalog,
    SchemaColumnDefinition,
    SchemaTableDefinition,
)
from retail_analytics_agent.metric_models import DatasetMetric, MetricStatus
from retail_analytics_agent.models import (
    AnalysisDimension,
    AnalysisFilterField,
    AnalysisMetric,
)


class DatasetScopeError(ValueError):
    """Base error for dataset analysis scope resolution."""


class DatasetScopeRejectionError(DatasetScopeError):
    """A dataset that cannot be analyzed yet, with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_METRIC_ID_MAP: dict[str, AnalysisMetric] = {
    "sales_amount": AnalysisMetric.SALES_AMOUNT,
    "order_count": AnalysisMetric.ORDER_COUNT,
    "units_sold": AnalysisMetric.UNITS_SOLD,
    "avg_order_value": AnalysisMetric.AVERAGE_ORDER_VALUE,
}

_DIMENSION_ROLE_MAP: dict[MappingRole, AnalysisDimension] = {
    MappingRole.CHANNEL: AnalysisDimension.CHANNEL,
    MappingRole.REGION: AnalysisDimension.REGION,
    MappingRole.CATEGORY: AnalysisDimension.CATEGORY,
}

_FILTER_ROLE_MAP: dict[MappingRole, AnalysisFilterField] = {
    MappingRole.CHANNEL: AnalysisFilterField.CHANNEL,
    MappingRole.CATEGORY: AnalysisFilterField.CATEGORY,
}


class DatasetScope(BaseModel):
    """Serializable per-dataset analysis scope consumed by the workflow.

    Every SQL/catalog contract in the analysis chain either uses this scope
    (dataset mode) or falls back to the fixed public demo catalog.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=80)
    dataset_version: int = Field(ge=1)
    dataset_name: str = Field(min_length=1, max_length=200)
    schema_name: str = Field(min_length=1, max_length=63)
    metric_catalog: MetricCatalog
    schema_catalog: SchemaCatalog
    allowed_columns: dict[str, tuple[str, ...]]
    dimension_columns: dict[AnalysisDimension, str]
    filter_columns: dict[AnalysisFilterField, str]
    time_column: str | None = None

    def sql_table(self, table_name: str) -> str:
        return f"{self.schema_name}.{table_name}"


def resolve_dataset_scope(
    record: DatasetRecord,
    mapping: DatasetMapping,
    metrics: tuple[DatasetMetric, ...],
    profile: SchemaProfile,
) -> DatasetScope:
    """Convert confirmed dataset metadata into the workflow analysis scope."""
    confirmed = tuple(item for item in metrics if item.status is MetricStatus.CONFIRMED)
    if not confirmed:
        raise DatasetScopeRejectionError(
            "dataset_no_metrics",
            "该数据集还没有已确认的分析指标。",
        )
    if not mapping.confirmed or not mapping.fields:
        raise DatasetScopeRejectionError(
            "dataset_mapping_unconfirmed",
            "该数据集尚未确认字段映射，不能用于分析。",
        )

    definitions = tuple(
        _metric_definition(item)
        for item in confirmed
        if item.metric_id in _METRIC_ID_MAP
    )
    if not definitions:
        raise DatasetScopeRejectionError(
            "dataset_no_metrics",
            "该数据集还没有可分析的有确认指标。",
        )
    role_sources = {field.role: field for field in mapping.fields}
    return DatasetScope(
        dataset_id=record.dataset_id,
        dataset_version=record.version,
        dataset_name=record.dataset_name,
        schema_name=record.schema_name,
        metric_catalog=MetricCatalog(definitions=definitions),
        schema_catalog=_schema_catalog(profile),
        allowed_columns=_allowed_columns(profile),
        dimension_columns=_dimension_columns(role_sources),
        filter_columns=_filter_columns(role_sources),
        time_column=_time_column(role_sources),
    )


class DatasetScopeResolver:
    """Resolve a requested dataset into a usable analysis scope."""

    def __init__(
        self,
        registry,
        profiler,
        connect: Callable,
    ) -> None:
        self._registry = registry
        self._profiler = profiler
        self._connect = connect

    def resolve(
        self,
        dataset_id: str,
        version: int | None = None,
    ) -> DatasetScope:
        record = self._registry.get(dataset_id, version)
        if record is None:
            raise DatasetScopeRejectionError(
                "dataset_not_found",
                "数据集版本不存在。",
            )
        if record.status is DatasetStatus.ARCHIVED:
            raise DatasetScopeRejectionError(
                "dataset_archived",
                "该数据集已归档，不能用于分析。",
            )
        if record.status is not DatasetStatus.READY:
            raise DatasetScopeRejectionError(
                "dataset_not_ready",
                "该数据集尚未完成质量检查与映射确认。",
            )
        if not record.mapping_confirmed or record.mapping is None:
            raise DatasetScopeRejectionError(
                "dataset_mapping_unconfirmed",
                "该数据集尚未确认字段映射。",
            )
        mapping = DatasetMapping.model_validate(record.mapping)
        metrics = self._registry.list_metrics(dataset_id, record.version)
        with self._connect() as connection:
            profile = self._profiler.inspect(record.schema_name, connection)
        return resolve_dataset_scope(record, mapping, metrics, profile)


def _metric_definition(metric: DatasetMetric) -> MetricDefinition:
    analysis_metric = _METRIC_ID_MAP[metric.metric_id]
    dimensions = tuple(
        _DIMENSION_ROLE_MAP[role]
        for role in metric.supported_dimensions
        if role in _DIMENSION_ROLE_MAP
    )
    formula_columns = _formula_columns(metric.formula)
    source_tables = tuple(
        dict.fromkeys(column.split(".", 1)[0] for column in formula_columns)
    )
    return MetricDefinition(
        metric=analysis_metric,
        version=metric.metric_version,
        display_name=metric.name,
        aliases=(metric.name,),
        description=metric.definition,
        formula=metric.formula,
        source_tables=source_tables,
        source_columns=formula_columns,
        supported_dimensions=dimensions,
    )


def _formula_columns(formula: str) -> tuple[str, ...]:
    expression = parse_one(formula, dialect="postgres")
    columns: list[str] = []
    for column in expression.find_all(exp.Column):
        if column.table:
            columns.append(f"{column.table}.{column.name}")
    return tuple(dict.fromkeys(columns))


def _schema_catalog(profile: SchemaProfile) -> SchemaCatalog:
    tables: list[SchemaTableDefinition] = []
    for table in profile.tables:
        identifier_columns = tuple(
            column.name
            for column in table.columns
            if "identifier" in column.candidate_roles
        )
        primary_key = (
            identifier_columns
            if identifier_columns
            else (table.columns[0].name,)
        )
        tables.append(
            SchemaTableDefinition(
                table_name=table.table_name,
                description=f"数据集 {profile.schema_name} 中的表 {table.table_name}",
                columns=tuple(
                    SchemaColumnDefinition(
                        name=column.name,
                        data_type=column.normalized_type,
                        description=column.name,
                    )
                    for column in table.columns
                ),
                primary_key=primary_key,
            )
        )
    return SchemaCatalog(tables=tuple(tables))


def _allowed_columns(profile: SchemaProfile) -> dict[str, tuple[str, ...]]:
    return {
        table.table_name: tuple(column.name for column in table.columns)
        for table in profile.tables
    }


def _dimension_columns(
    role_sources: Mapping[MappingRole, MappingField],
) -> dict[AnalysisDimension, str]:
    return {
        dimension: f"{field.table}.{field.column}"
        for role, dimension in _DIMENSION_ROLE_MAP.items()
        if (field := role_sources.get(role)) is not None
    }


def _filter_columns(
    role_sources: Mapping[MappingRole, MappingField],
) -> dict[AnalysisFilterField, str]:
    return {
        field_name: f"{field.table}.{field.column}"
        for role, field_name in _FILTER_ROLE_MAP.items()
        if (field := role_sources.get(role)) is not None
    }


def _time_column(
    role_sources: Mapping[MappingRole, MappingField],
) -> str | None:
    field = role_sources.get(MappingRole.TIME)
    if field is None:
        return None
    return f"{field.table}.{field.column}"
