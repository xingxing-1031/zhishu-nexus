from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from retail_analytics_agent.dataset_mapping import (
    DatasetMapping,
    MappingField,
    MappingRole,
)
from retail_analytics_agent.dataset_models import (
    DatasetRecord,
    DatasetSourceType,
    DatasetStatus,
    QualityReport,
)
from retail_analytics_agent.dataset_registry import (
    DatasetRegistry,
    DatasetStatusTransitionError,
)


def _record(
    *,
    dataset_id: str = "olist",
    version: int = 1,
    status: DatasetStatus = DatasetStatus.UPLOADED,
) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        dataset_name="Olist sales",
        source_type=DatasetSourceType.CSV,
        source_ref="uploads/olist.csv",
        schema_name=f"staging_{dataset_id}_{version}",
        version=version,
        status=status,
        row_count=12,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        updated_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def _db_row(record: DatasetRecord) -> dict[str, object]:
    return {
        "dataset_id": record.dataset_id,
        "dataset_name": record.dataset_name,
        "source_type": record.source_type.value,
        "source_ref": record.source_ref,
        "schema_name": record.schema_name,
        "version": record.version,
        "status": record.status.value,
        "row_count": record.row_count,
        "quality_report": record.quality_report,
        "mapping": record.mapping,
        "mapping_confirmed": record.mapping_confirmed,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _registry_with_connection(
    connection: MagicMock,
) -> DatasetRegistry:
    connection.__enter__.return_value = connection
    return DatasetRegistry(connect=lambda: connection)


def test_registry_migration_defines_dataset_and_quality_tables() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "011_dataset_registry.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE dataset_registry" in sql
    assert "PRIMARY KEY (dataset_id, version)" in sql
    assert "CREATE TABLE dataset_quality_reports" in sql
    assert "CONSTRAINT dataset_status_valid" in sql
    for status in ("uploaded", "profiling", "needs_mapping", "ready", "failed", "archived"):
        assert f"'{status}'" in sql

    mapping_sql = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "012_dataset_mapping.sql"
    ).read_text(encoding="utf-8")
    assert "ADD COLUMN mapping JSONB" in mapping_sql
    assert "mapping_confirmed BOOLEAN NOT NULL DEFAULT FALSE" in mapping_sql


def test_create_is_idempotent_for_dataset_and_version() -> None:
    connection = MagicMock()
    first = _record()
    connection.execute.return_value.fetchone.side_effect = [
        _db_row(first),
        _db_row(first),
    ]
    registry = _registry_with_connection(connection)

    created = registry.create(first)
    repeated = registry.create(first)

    assert created == first
    assert repeated == first
    assert connection.execute.call_count == 2
    insert_params = connection.execute.call_args_list[0].args[1]
    assert insert_params["dataset_id"] == "olist"
    assert insert_params["schema_name"] == "staging_olist_1"


def test_status_update_rejects_skipping_required_mapping_step() -> None:
    connection = MagicMock()
    current = _record(status=DatasetStatus.PROFILING)
    connection.execute.return_value.fetchone.return_value = _db_row(current)
    registry = _registry_with_connection(connection)

    with pytest.raises(DatasetStatusTransitionError, match="profiling -> ready"):
        registry.update_status("olist", DatasetStatus.READY)

    assert connection.execute.call_count == 1


def test_status_update_persists_quality_report_and_returns_new_record() -> None:
    connection = MagicMock()
    current = _record(status=DatasetStatus.NEEDS_MAPPING)
    ready = _record(status=DatasetStatus.READY)
    connection.execute.return_value.fetchone.side_effect = [
        _db_row(current),
        _db_row(ready),
    ]
    registry = _registry_with_connection(connection)
    quality = QualityReport(passed=True, checked_rows=12)

    result = registry.update_status(
        "olist",
        DatasetStatus.READY,
        quality_report=quality,
    )

    assert result.status is DatasetStatus.READY
    update_params = connection.execute.call_args_list[1].args[1]
    assert update_params["status"] == "ready"
    assert update_params["quality_report"].obj["passed"] is True


def test_list_active_excludes_archived_datasets() -> None:
    connection = MagicMock()
    ready = _record(status=DatasetStatus.READY)
    connection.execute.return_value.fetchall.return_value = [_db_row(ready)]
    registry = _registry_with_connection(connection)

    active = registry.list_active()

    assert active == (ready,)
    sql = connection.execute.call_args.args[0]
    assert "status <> 'archived'" in sql


def test_invalid_schema_is_rejected_before_database_execution() -> None:
    connection = MagicMock()
    registry = _registry_with_connection(connection)

    with pytest.raises(ValueError, match="schema_name"):
        registry.create(
            DatasetRecord(
                dataset_id="olist",
                dataset_name="Olist sales",
                source_type=DatasetSourceType.CSV,
                schema_name="staging_olist;drop_table",
                version=1,
            )
        )

    connection.execute.assert_not_called()


def test_save_mapping_persists_confirmation_separately_from_dataset_status() -> None:
    connection = MagicMock()
    current = _record()
    mapped = current.model_copy(
        update={
            "mapping": {
                "dataset_id": "olist",
                "version": 1,
                "mapping_version": "v1",
                "fields": [
                    {
                        "role": "amount",
                        "table": "dataset_rows",
                        "column": "total_amount",
                        "confidence": 0.95,
                        "reasons": [],
                    }
                ],
                "confirmed": True,
            },
            "mapping_confirmed": True,
        }
    )
    connection.execute.return_value.fetchone.side_effect = [
        _db_row(current),
        _db_row(mapped),
    ]
    registry = _registry_with_connection(connection)
    mapping = DatasetMapping(
        dataset_id="olist",
        version=1,
        fields=(
            MappingField(
                role=MappingRole.AMOUNT,
                table="dataset_rows",
                column="total_amount",
                confidence=0.95,
            ),
        ),
    )

    result = registry.save_mapping(mapping, confirmed=True)

    assert result.mapping_confirmed is True
    params = connection.execute.call_args_list[1].args[1]
    assert params["mapping_confirmed"] is True
    assert params["mapping"].obj["confirmed"] is True
