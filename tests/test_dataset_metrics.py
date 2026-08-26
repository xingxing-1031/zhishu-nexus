from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from retail_analytics_agent.dataset_mapping import (
    DatasetMapping,
    MappingField,
    MappingRole,
)
from retail_analytics_agent.dataset_models import (
    ColumnProfile,
    SchemaProfile,
    TableProfile,
)
from retail_analytics_agent.dataset_registry import (
    DatasetMetricNotFoundError,
    DatasetRegistry,
)
from retail_analytics_agent.metric_models import (
    DatasetMetric,
    MetricStatus,
    MetricValidationError,
    as_confirmed,
    has_confirmed_metric,
    propose_metrics,
    validate_metrics,
    with_latest_version,
)


def _profile(
    columns: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> SchemaProfile:
    return SchemaProfile(
        schema_name="staging_demo_1",
        tables=(
            TableProfile(
                table_name="dataset_rows",
                row_count=2,
                columns=tuple(
                    ColumnProfile(
                        name=name,
                        normalized_type=column_type,
                        null_ratio=0,
                        unique_ratio=0.5,
                        candidate_roles=roles,
                    )
                    for name, column_type, roles in columns
                ),
            ),
        ),
    )


def _mapping(
    dataset_id: str,
    fields: tuple[tuple[MappingRole, str], ...],
) -> DatasetMapping:
    return DatasetMapping(
        dataset_id=dataset_id,
        version=1,
        fields=tuple(
            MappingField(
                role=role,
                table="dataset_rows",
                column=column,
                confidence=0.9,
            )
            for role, column in fields
        ),
        confirmed=True,
    )


def _sales_metric(
    *,
    status: MetricStatus = MetricStatus.PROPOSED,
    version: str = "v1",
) -> DatasetMetric:
    return DatasetMetric(
        dataset_id="demo",
        dataset_version=1,
        metric_id="sales_amount",
        metric_version=version,
        name="销售额",
        definition="销售额为已确认金额字段的合计。",
        aggregation="SUM",
        formula="SUM(dataset_rows.total_amount)",
        source_role=MappingRole.AMOUNT,
        source_table="dataset_rows",
        source_column="total_amount",
        status=status,
    )


def _metric_row(metric: DatasetMetric) -> dict[str, object]:
    return {
        "dataset_id": metric.dataset_id,
        "dataset_version": metric.dataset_version,
        "metric_id": metric.metric_id,
        "metric_version": metric.metric_version,
        "name": metric.name,
        "definition": metric.definition,
        "aggregation": metric.aggregation,
        "formula": metric.formula,
        "source_role": metric.source_role.value,
        "source_table": metric.source_table,
        "source_column": metric.source_column,
        "supported_dimensions": [
            dimension.value for dimension in metric.supported_dimensions
        ],
        "fixed_filters": list(metric.fixed_filters),
        "status": metric.status.value,
        "effective_from": metric.effective_from,
        "confirmed_by": metric.confirmed_by,
        "confirmed_at": metric.confirmed_at,
        "created_at": datetime(2026, 8, 26, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 26, tzinfo=UTC),
    }


def _registry_with_connection(connection: MagicMock) -> DatasetRegistry:
    connection.__enter__.return_value = connection
    return DatasetRegistry(connect=lambda: connection)


def test_two_naming_conventions_produce_same_sales_metric() -> None:
    profile_a = _profile(
        (
            ("total_amount", "numeric", ("amount",)),
            ("order_id", "text", ("identifier",)),
            ("sales_channel", "text", ("categorical",)),
            ("ordered_at", "timestamp", ("time",)),
        )
    )
    mapping_a = _mapping(
        "dataset_a",
        (
            (MappingRole.AMOUNT, "total_amount"),
            (MappingRole.ORDER_ID, "order_id"),
            (MappingRole.CHANNEL, "sales_channel"),
            (MappingRole.TIME, "ordered_at"),
        ),
    )
    profile_b = _profile(
        (
            ("revenue", "integer", ("amount",)),
            ("txn_no", "text", ("identifier",)),
            ("source", "text", ("categorical",)),
            ("transaction_date", "date", ("time",)),
        )
    )
    mapping_b = _mapping(
        "dataset_b",
        (
            (MappingRole.AMOUNT, "revenue"),
            (MappingRole.ORDER_ID, "txn_no"),
            (MappingRole.CHANNEL, "source"),
            (MappingRole.TIME, "transaction_date"),
        ),
    )

    metrics_a = propose_metrics("dataset_a", 1, mapping_a, profile_a)
    metrics_b = propose_metrics("dataset_b", 1, mapping_b, profile_b)

    sales_a = next(item for item in metrics_a if item.metric_id == "sales_amount")
    sales_b = next(item for item in metrics_b if item.metric_id == "sales_amount")
    assert sales_a.metric_id == sales_b.metric_id == "sales_amount"
    assert sales_a.formula == "SUM(dataset_rows.total_amount)"
    assert sales_b.formula == "SUM(dataset_rows.revenue)"
    assert {dim.value for dim in sales_a.supported_dimensions} == {"channel"}


def test_missing_order_id_skips_order_count_and_avg_order_value() -> None:
    profile = _profile(
        (
            ("total_amount", "numeric", ("amount",)),
            ("sales_channel", "text", ("categorical",)),
        )
    )
    mapping = _mapping(
        "demo",
        (
            (MappingRole.AMOUNT, "total_amount"),
            (MappingRole.CHANNEL, "sales_channel"),
        ),
    )

    metrics = propose_metrics("demo", 1, mapping, profile)

    metric_ids = {item.metric_id for item in metrics}
    assert "sales_amount" in metric_ids
    assert "order_count" not in metric_ids
    assert "avg_order_value" not in metric_ids


def test_validate_rejects_incompatible_column_type() -> None:
    profile = _profile((("total_amount", "text", ("categorical",)),))
    mapping = _mapping("demo", ((MappingRole.AMOUNT, "total_amount"),))

    metrics = propose_metrics("demo", 1, mapping, profile)

    with pytest.raises(MetricValidationError, match="type compatible"):
        validate_metrics(metrics, mapping, profile)


def test_validate_rejects_metric_with_unknown_dimension() -> None:
    profile = _profile((("total_amount", "numeric", ("amount",)),))
    mapping = _mapping("demo", ((MappingRole.AMOUNT, "total_amount"),))
    metric = _sales_metric().model_copy(
        update={"supported_dimensions": (MappingRole.REGION,)}
    )

    with pytest.raises(MetricValidationError, match="dimension is not confirmed"):
        validate_metrics((metric,), mapping, profile)


def test_unconfirmed_metric_is_not_usable_until_confirmed() -> None:
    profile = _profile(
        (
            ("total_amount", "numeric", ("amount",)),
            ("order_id", "text", ("identifier",)),
        )
    )
    mapping = _mapping(
        "demo",
        (
            (MappingRole.AMOUNT, "total_amount"),
            (MappingRole.ORDER_ID, "order_id"),
        ),
    )

    metrics = propose_metrics("demo", 1, mapping, profile)

    assert all(item.status is MetricStatus.PROPOSED for item in metrics)
    assert has_confirmed_metric(metrics) is False

    confirmed = tuple(as_confirmed(item, "admin-1") for item in metrics)
    assert has_confirmed_metric(confirmed) is True
    assert all(item.confirmed_by == "admin-1" for item in confirmed)
    assert all(item.status is MetricStatus.CONFIRMED for item in confirmed)


def test_metric_version_bump_keeps_source_id_stable() -> None:
    profile = _profile(
        (
            ("total_amount", "numeric", ("amount",)),
            ("order_id", "text", ("identifier",)),
        )
    )
    mapping = _mapping(
        "demo",
        (
            (MappingRole.AMOUNT, "total_amount"),
            (MappingRole.ORDER_ID, "order_id"),
        ),
    )

    first = propose_metrics("demo", 1, mapping, profile)
    existing = first[:1]
    second = propose_metrics("demo", 1, mapping, profile)
    bumped = tuple(with_latest_version(item, existing) for item in second)

    sales_v2 = next(item for item in bumped if item.metric_id == "sales_amount")
    assert sales_v2.metric_version == "v2"
    assert sales_v2.source_id == "metric.demo.v1.sales_amount.v2"
    assert first[0].source_id == "metric.demo.v1.sales_amount.v1"
    assert sales_v2.source_id != first[0].source_id

    confirmed_v1 = as_confirmed(first[0], "admin-1")
    assert confirmed_v1.source_id == first[0].source_id
    assert confirmed_v1.status is MetricStatus.CONFIRMED


def test_metric_migration_defines_versioned_metric_table() -> None:
    sql = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "013_dataset_metric_versions.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE dataset_metric_versions" in sql
    assert (
        "PRIMARY KEY (dataset_id, dataset_version, metric_id, metric_version)" in sql
    )
    assert "status TEXT NOT NULL DEFAULT 'proposed'" in sql
    assert "metric_version ~ '^v[1-9][0-9]*$'" in sql


def test_save_metric_persists_metric_row() -> None:
    connection = MagicMock()
    metric = _sales_metric()
    connection.execute.return_value.fetchone.return_value = _metric_row(metric)
    registry = _registry_with_connection(connection)

    saved = registry.save_metric(metric)

    assert saved == metric
    params = connection.execute.call_args.args[1]
    assert params["metric_id"] == "sales_amount"
    assert params["status"] == "proposed"
    assert params["supported_dimensions"].obj == []


def test_confirm_metric_promotes_latest_proposed_version() -> None:
    connection = MagicMock()
    proposed = _sales_metric(status=MetricStatus.PROPOSED)
    confirmed = as_confirmed(proposed, "admin-1")
    connection.execute.return_value.fetchall.return_value = [_metric_row(proposed)]
    connection.execute.return_value.fetchone.return_value = _metric_row(confirmed)
    registry = _registry_with_connection(connection)

    result = registry.confirm_metric("demo", 1, "sales_amount", "admin-1")

    assert result.status is MetricStatus.CONFIRMED
    assert result.confirmed_by == "admin-1"
    update_params = connection.execute.call_args_list[1].args[1]
    assert update_params["metric_id"] == "sales_amount"
    assert update_params["metric_version"] == "v1"
    assert update_params["confirmed_by"] == "admin-1"


def test_confirm_metric_is_idempotent_when_already_confirmed() -> None:
    connection = MagicMock()
    confirmed = _sales_metric(status=MetricStatus.CONFIRMED)
    connection.execute.return_value.fetchall.return_value = [_metric_row(confirmed)]
    registry = _registry_with_connection(connection)

    result = registry.confirm_metric("demo", 1, "sales_amount", "admin-1")

    assert result.status is MetricStatus.CONFIRMED
    assert connection.execute.call_count == 1


def test_confirm_metric_raises_when_metric_does_not_exist() -> None:
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = []
    registry = _registry_with_connection(connection)

    with pytest.raises(DatasetMetricNotFoundError, match="metric not found"):
        registry.confirm_metric("demo", 1, "sales_amount", "admin-1")
