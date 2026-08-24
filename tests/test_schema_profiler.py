from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from retail_analytics_agent.dataset_models import QualitySeverity
from retail_analytics_agent.schema_profiler import (
    SchemaProfiler,
    UnvalidatedSchemaError,
)


class _Result:
    def __init__(self, *, rows: list[dict[str, Any]] | None = None, row: dict[str, Any] | None = None) -> None:
        self._rows = rows or []
        self._row = row

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _ProfilerConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.tables = [{"table_name": "orders"}]
        self.columns = [
            {"table_name": "orders", "column_name": "order_id", "data_type": "text"},
            {"table_name": "orders", "column_name": "amount", "data_type": "numeric"},
            {"table_name": "orders", "column_name": "created_at", "data_type": "timestamp with time zone"},
            {"table_name": "orders", "column_name": "channel", "data_type": "text"},
        ]
        self.samples = [
            {
                "order_id": "A-1",
                "amount": Decimal("12.50"),
                "created_at": datetime(2026, 8, 1),
                "channel": "web",
            },
            {
                "order_id": "A-1",
                "amount": Decimal("-1.00"),
                "created_at": datetime(1800, 1, 1),
                "channel": None,
            },
        ]

    def __enter__(self) -> "_ProfilerConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: object, params: Any = None) -> _Result:
        statement = str(query)
        self.calls.append((statement, params))
        if "information_schema.tables" in statement:
            return _Result(rows=self.tables)
        if "information_schema.columns" in statement:
            return _Result(rows=self.columns)
        if "COUNT(*)" in statement:
            return _Result(row={"row_count": len(self.samples)})
        if "SELECT *" in statement:
            return _Result(rows=self.samples)
        raise AssertionError(f"unexpected query: {statement}")


def test_inspect_returns_profiles_and_candidate_roles() -> None:
    connection = _ProfilerConnection()
    profile = SchemaProfiler().inspect("staging_demo_1", connection)

    table = profile.tables[0]
    by_name = {column.name: column for column in table.columns}
    assert table.row_count == 2
    assert "identifier" in by_name["order_id"].candidate_roles
    assert "amount" in by_name["amount"].candidate_roles
    assert "time" in by_name["created_at"].candidate_roles
    assert "categorical" in by_name["channel"].candidate_roles
    assert by_name["channel"].null_ratio == 0.5
    assert by_name["order_id"].unique_ratio == 0.5
    assert by_name["amount"].sample_values == (Decimal("12.50"), Decimal("-1.00"))


def test_quality_reports_empty_table_duplicate_identifier_and_bad_timestamp() -> None:
    connection = _ProfilerConnection()
    report = SchemaProfiler().quality("staging_demo_1", connection)

    codes = {issue.code for issue in report.issues}
    assert report.passed is False
    assert "non_unique_identifier" in codes
    assert "invalid_timestamp_range" in codes
    assert "negative_amount" in codes
    assert any(issue.severity is QualitySeverity.CRITICAL for issue in report.issues)


def test_quality_marks_empty_schema_as_critical() -> None:
    connection = _ProfilerConnection()
    connection.tables = []

    report = SchemaProfiler().quality("staging_demo_1", connection)

    assert report.passed is False
    assert report.issues[0].code == "empty_schema"
    assert report.issues[0].severity is QualitySeverity.CRITICAL


def test_unvalidated_schema_is_rejected_before_database_execution() -> None:
    connection = _ProfilerConnection()

    with pytest.raises(UnvalidatedSchemaError):
        SchemaProfiler().inspect("public", connection)

    assert connection.calls == []

