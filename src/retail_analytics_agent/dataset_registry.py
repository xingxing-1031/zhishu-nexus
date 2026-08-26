from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from psycopg.types.json import Jsonb

from retail_analytics_agent.database import DatabaseConnection, connect_to_database
from retail_analytics_agent.dataset_mapping import DatasetMapping
from retail_analytics_agent.dataset_models import (
    DatasetRecord,
    DatasetStatus,
    QualityReport,
)
from retail_analytics_agent.metric_models import (
    DatasetMetric,
    MetricStatus,
    metric_version_number,
)


class DatasetRegistryError(RuntimeError):
    """Base error for dataset metadata operations."""


class DatasetNotFoundError(DatasetRegistryError):
    """Raised when a requested dataset version does not exist."""


class DatasetStatusTransitionError(DatasetRegistryError):
    """Raised when a dataset status skips a required onboarding step."""


class DatasetMetricNotFoundError(DatasetRegistryError):
    """Raised when a dataset metric version does not exist."""


_ALLOWED_TRANSITIONS: dict[DatasetStatus, frozenset[DatasetStatus]] = {
    DatasetStatus.UPLOADED: frozenset({DatasetStatus.PROFILING, DatasetStatus.FAILED}),
    DatasetStatus.PROFILING: frozenset({DatasetStatus.NEEDS_MAPPING, DatasetStatus.FAILED}),
    DatasetStatus.NEEDS_MAPPING: frozenset({DatasetStatus.READY, DatasetStatus.FAILED}),
    DatasetStatus.READY: frozenset({DatasetStatus.ARCHIVED}),
    DatasetStatus.FAILED: frozenset({DatasetStatus.PROFILING, DatasetStatus.ARCHIVED}),
    DatasetStatus.ARCHIVED: frozenset(),
}


CREATE_DATASET_SQL = """
INSERT INTO dataset_registry (
    dataset_id, dataset_name, source_type, source_ref, schema_name,
    version, status, row_count, quality_report
)
VALUES (
    %(dataset_id)s, %(dataset_name)s, %(source_type)s, %(source_ref)s,
    %(schema_name)s, %(version)s, %(status)s, %(row_count)s,
    %(quality_report)s
)
ON CONFLICT (dataset_id, version) DO UPDATE SET
    updated_at = dataset_registry.updated_at
RETURNING *;
"""

GET_DATASET_SQL = """
SELECT *
FROM dataset_registry
WHERE dataset_id = %(dataset_id)s AND version = %(version)s;
"""

GET_LATEST_DATASET_SQL = """
SELECT *
FROM dataset_registry
WHERE dataset_id = %(dataset_id)s
ORDER BY version DESC
LIMIT 1;
"""

LIST_ACTIVE_DATASETS_SQL = """
SELECT *
FROM dataset_registry
WHERE status <> 'archived'
ORDER BY dataset_id, version DESC;
"""

UPDATE_DATASET_STATUS_SQL = """
UPDATE dataset_registry
SET status = %(status)s,
    quality_report = COALESCE(%(quality_report)s, quality_report),
    updated_at = CURRENT_TIMESTAMP
WHERE dataset_id = %(dataset_id)s AND version = %(version)s
RETURNING *;
"""

SAVE_DATASET_MAPPING_SQL = """
UPDATE dataset_registry
SET mapping = %(mapping)s,
    mapping_confirmed = %(mapping_confirmed)s,
    updated_at = CURRENT_TIMESTAMP
WHERE dataset_id = %(dataset_id)s AND version = %(version)s
RETURNING *;
"""

INSERT_QUALITY_REPORT_SQL = """
INSERT INTO dataset_quality_reports (dataset_id, version, report)
VALUES (%(dataset_id)s, %(version)s, %(report)s);
"""

INSERT_METRIC_SQL = """
INSERT INTO dataset_metric_versions (
    dataset_id, dataset_version, metric_id, metric_version,
    name, definition, aggregation, formula,
    source_role, source_table, source_column,
    supported_dimensions, fixed_filters, status,
    effective_from, confirmed_by, confirmed_at
)
VALUES (
    %(dataset_id)s, %(dataset_version)s, %(metric_id)s, %(metric_version)s,
    %(name)s, %(definition)s, %(aggregation)s, %(formula)s,
    %(source_role)s, %(source_table)s, %(source_column)s,
    %(supported_dimensions)s, %(fixed_filters)s, %(status)s,
    %(effective_from)s, %(confirmed_by)s, %(confirmed_at)s
)
ON CONFLICT (dataset_id, dataset_version, metric_id, metric_version) DO UPDATE SET
    updated_at = dataset_metric_versions.updated_at
RETURNING *;
"""

LIST_METRICS_SQL = """
SELECT *
FROM dataset_metric_versions
WHERE dataset_id = %(dataset_id)s AND dataset_version = %(dataset_version)s
ORDER BY metric_id, metric_version;
"""

CONFIRM_METRIC_SQL = """
UPDATE dataset_metric_versions
SET status = 'confirmed',
    confirmed_by = %(confirmed_by)s,
    confirmed_at = CURRENT_TIMESTAMP,
    effective_from = COALESCE(effective_from, CURRENT_TIMESTAMP),
    updated_at = CURRENT_TIMESTAMP
WHERE dataset_id = %(dataset_id)s
  AND dataset_version = %(dataset_version)s
  AND metric_id = %(metric_id)s
  AND metric_version = %(metric_version)s
RETURNING *;
"""


@dataclass(frozen=True)
class DatasetRegistry:
    """Persist dataset metadata without touching imported business tables."""

    connect: Callable[[], DatabaseConnection] = connect_to_database

    def create(self, record: DatasetRecord) -> DatasetRecord:
        params = _record_params(record)
        with self.connect() as connection:
            row = connection.execute(CREATE_DATASET_SQL, params).fetchone()
        if row is None:
            raise DatasetRegistryError("dataset registry did not return a record")
        return _record_from_row(row)

    def get(
        self,
        dataset_id: str,
        version: int | None = None,
    ) -> DatasetRecord | None:
        sql = GET_DATASET_SQL if version is not None else GET_LATEST_DATASET_SQL
        params = {"dataset_id": dataset_id}
        if version is not None:
            params["version"] = version
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return _record_from_row(row) if row is not None else None

    def update_status(
        self,
        dataset_id: str,
        status: DatasetStatus,
        *,
        version: int | None = None,
        quality_report: QualityReport | None = None,
    ) -> DatasetRecord:
        current = self.get(dataset_id, version)
        if current is None:
            raise DatasetNotFoundError(f"dataset not found: {dataset_id}")
        allowed = _ALLOWED_TRANSITIONS[current.status]
        if status not in allowed:
            raise DatasetStatusTransitionError(
                f"invalid dataset status transition: "
                f"{current.status.value} -> {status.value}"
            )
        if status is DatasetStatus.READY and (
            quality_report is None or not quality_report.passed
        ):
            raise DatasetStatusTransitionError(
                "dataset can become ready only with a passing quality report"
            )

        report_json = (
            Jsonb(quality_report.model_dump(mode="json"))
            if quality_report is not None
            else None
        )
        params = {
            "dataset_id": current.dataset_id,
            "version": current.version,
            "status": status.value,
            "quality_report": report_json,
        }
        with self.connect() as connection:
            with connection.transaction():
                row = connection.execute(
                    UPDATE_DATASET_STATUS_SQL,
                    params,
                ).fetchone()
                if row is None:
                    raise DatasetRegistryError("dataset status update returned no record")
                if quality_report is not None:
                    connection.execute(
                        INSERT_QUALITY_REPORT_SQL,
                        {
                            "dataset_id": current.dataset_id,
                            "version": current.version,
                            "report": report_json,
                        },
                    )
        return _record_from_row(row)

    def save_mapping(
        self,
        mapping: DatasetMapping,
        *,
        confirmed: bool = False,
    ) -> DatasetRecord:
        current = self.get(mapping.dataset_id, mapping.version)
        if current is None:
            raise DatasetNotFoundError(f"dataset not found: {mapping.dataset_id}")
        mapping_payload = mapping.model_copy(update={"confirmed": confirmed})
        with self.connect() as connection:
            row = connection.execute(
                SAVE_DATASET_MAPPING_SQL,
                {
                    "dataset_id": mapping.dataset_id,
                    "version": mapping.version,
                    "mapping": Jsonb(mapping_payload.model_dump(mode="json")),
                    "mapping_confirmed": confirmed,
                },
            ).fetchone()
        if row is None:
            raise DatasetRegistryError("dataset mapping update returned no record")
        return _record_from_row(row)

    def save_metric(self, metric: DatasetMetric) -> DatasetMetric:
        with self.connect() as connection:
            row = connection.execute(
                INSERT_METRIC_SQL,
                _metric_params(metric),
            ).fetchone()
        if row is None:
            raise DatasetRegistryError("dataset metric insert returned no record")
        return _metric_from_row(row)

    def list_metrics(
        self,
        dataset_id: str,
        version: int,
    ) -> tuple[DatasetMetric, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                LIST_METRICS_SQL,
                {"dataset_id": dataset_id, "dataset_version": version},
            ).fetchall()
        return tuple(_metric_from_row(row) for row in rows)

    def confirm_metric(
        self,
        dataset_id: str,
        version: int,
        metric_id: str,
        confirmed_by: str,
    ) -> DatasetMetric:
        metrics = self.list_metrics(dataset_id, version)
        matching = [item for item in metrics if item.metric_id == metric_id]
        if not matching:
            raise DatasetMetricNotFoundError(f"metric not found: {metric_id}")
        latest = max(
            matching,
            key=lambda item: metric_version_number(item.metric_version),
        )
        if latest.status is MetricStatus.CONFIRMED:
            return latest
        with self.connect() as connection:
            row = connection.execute(
                CONFIRM_METRIC_SQL,
                {
                    "dataset_id": dataset_id,
                    "dataset_version": version,
                    "metric_id": metric_id,
                    "metric_version": latest.metric_version,
                    "confirmed_by": confirmed_by,
                },
            ).fetchone()
        if row is None:
            raise DatasetRegistryError("dataset metric confirm returned no record")
        return _metric_from_row(row)

    def list_active(self) -> tuple[DatasetRecord, ...]:
        with self.connect() as connection:
            rows = connection.execute(LIST_ACTIVE_DATASETS_SQL).fetchall()
        return tuple(_record_from_row(row) for row in rows)


def _record_params(record: DatasetRecord) -> dict[str, object]:
    quality_report = (
        Jsonb(record.quality_report) if record.quality_report is not None else None
    )
    return {
        "dataset_id": record.dataset_id,
        "dataset_name": record.dataset_name,
        "source_type": record.source_type.value,
        "source_ref": record.source_ref,
        "schema_name": record.schema_name,
        "version": record.version,
        "status": record.status.value,
        "row_count": record.row_count,
        "quality_report": quality_report,
    }


def _record_from_row(row: dict[str, object]) -> DatasetRecord:
    return DatasetRecord.model_validate(dict(row))


_METRIC_COLUMNS = (
    "dataset_id",
    "dataset_version",
    "metric_id",
    "metric_version",
    "name",
    "definition",
    "aggregation",
    "formula",
    "source_role",
    "source_table",
    "source_column",
    "supported_dimensions",
    "fixed_filters",
    "status",
    "effective_from",
    "confirmed_by",
    "confirmed_at",
)


def _metric_params(metric: DatasetMetric) -> dict[str, object]:
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
        "supported_dimensions": Jsonb(
            [dimension.value for dimension in metric.supported_dimensions]
        ),
        "fixed_filters": Jsonb(list(metric.fixed_filters)),
        "status": metric.status.value,
        "effective_from": metric.effective_from,
        "confirmed_by": metric.confirmed_by,
        "confirmed_at": metric.confirmed_at,
    }


def _metric_from_row(row: dict[str, object]) -> DatasetMetric:
    return DatasetMetric.model_validate(
        {key: row[key] for key in _METRIC_COLUMNS if key in row}
    )


def get_dataset_registry() -> DatasetRegistry:
    return DatasetRegistry()
