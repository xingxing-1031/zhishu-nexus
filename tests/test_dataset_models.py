from decimal import Decimal

import pytest
from pydantic import ValidationError

from retail_analytics_agent.dataset_models import (
    ColumnProfile,
    DatasetRecord,
    DatasetSourceType,
    DatasetStatus,
    QualityIssue,
    QualityReport,
    QualitySeverity,
    SchemaProfile,
    TableProfile,
)


def test_dataset_record_accepts_valid_metadata() -> None:
    record = DatasetRecord(
        dataset_id="olist",
        dataset_name="Olist sales",
        source_type=DatasetSourceType.POSTGRES,
        schema_name="staging_olist_2026",
        version=1,
        status=DatasetStatus.UPLOADED,
        row_count=10,
    )

    assert record.dataset_id == "olist"
    assert record.status is DatasetStatus.UPLOADED
    assert record.row_count == 10


def test_dataset_record_rejects_unknown_fields_and_invalid_schema() -> None:
    with pytest.raises(ValidationError):
        DatasetRecord(
            dataset_id="olist",
            dataset_name="Olist sales",
            source_type="postgres",
            schema_name="public;drop table orders",
            version=1,
            status="uploaded",
            row_count=10,
            unexpected=True,
        )


def test_quality_report_preserves_issue_location_and_severity() -> None:
    report = QualityReport(
        passed=False,
        checked_rows=12,
        issues=(
            QualityIssue(
                code="high_null_ratio",
                severity=QualitySeverity.WARNING,
                message="channel contains many null values",
                table="orders",
                column="channel",
            ),
        ),
    )

    assert report.issues[0].table == "orders"
    assert report.issues[0].severity is QualitySeverity.WARNING


def test_schema_profile_contains_table_and_column_profiles() -> None:
    profile = SchemaProfile(
        schema_name="staging_olist_2026",
        tables=(
            TableProfile(
                table_name="orders",
                row_count=2,
                columns=(
                    ColumnProfile(
                        name="total_amount",
                        normalized_type="numeric",
                        null_ratio=0,
                        unique_ratio=1,
                        sample_values=(Decimal("10.5"),),
                        candidate_roles=("amount",),
                    ),
                ),
            ),
        ),
    )

    assert profile.tables[0].columns[0].candidate_roles == ("amount",)
