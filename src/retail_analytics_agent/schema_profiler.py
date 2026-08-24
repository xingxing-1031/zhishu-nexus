from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import sql

from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.dataset_models import (
    ColumnProfile,
    QualityIssue,
    QualityReport,
    QualitySeverity,
    SchemaProfile,
    TableProfile,
)


class SchemaProfilerError(ValueError):
    """Base error for schema inspection."""


class UnvalidatedSchemaError(SchemaProfilerError):
    """Raised when inspection is attempted outside an isolated staging schema."""


_STAGING_SCHEMA_PATTERN = re.compile(r"staging_[a-z0-9_]+")
_SAMPLE_LIMIT = 200
_TEXT_TYPES = {"text", "character varying", "character", "USER-DEFINED"}
_TIME_TYPES = {
    "date",
    "time without time zone",
    "time with time zone",
    "timestamp without time zone",
    "timestamp with time zone",
}


@dataclass(frozen=True)
class SchemaProfiler:
    sample_limit: int = _SAMPLE_LIMIT

    def inspect(
        self,
        schema_name: str,
        connection: DatabaseConnection,
    ) -> SchemaProfile:
        _validate_staging_schema(schema_name)
        table_rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %(schema_name)s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            {"schema_name": schema_name},
        ).fetchall()
        column_rows = connection.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %(schema_name)s
            ORDER BY table_name, ordinal_position
            """,
            {"schema_name": schema_name},
        ).fetchall()
        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        for row in column_rows:
            columns_by_table.setdefault(row["table_name"], []).append(row)

        tables: list[TableProfile] = []
        for table_row in table_rows:
            table_name = table_row["table_name"]
            qualified_table = sql.Identifier(schema_name, table_name)
            count_row = connection.execute(
                sql.SQL("SELECT COUNT(*) AS row_count FROM {}")
                .format(qualified_table)
            ).fetchone()
            row_count = int((count_row or {}).get("row_count", 0))
            samples = connection.execute(
                sql.SQL("SELECT * FROM {} LIMIT %s")
                .format(qualified_table),
                (self.sample_limit,),
            ).fetchall()
            table_columns = columns_by_table.get(table_name, [])
            profiles = tuple(
                self._column_profile(
                    row,
                    samples,
                )
                for row in table_columns
            )
            tables.append(
                TableProfile(
                    table_name=table_name,
                    row_count=row_count,
                    columns=profiles,
                )
            )
        return SchemaProfile(schema_name=schema_name, tables=tuple(tables))

    def quality(
        self,
        schema_name: str,
        connection: DatabaseConnection,
    ) -> QualityReport:
        profile = self.inspect(schema_name, connection)
        issues: list[QualityIssue] = []
        checked_rows = sum(table.row_count for table in profile.tables)
        if not profile.tables:
            issues.append(
                QualityIssue(
                    code="empty_schema",
                    severity=QualitySeverity.CRITICAL,
                    message="staging schema contains no tables",
                    table="_schema",
                )
            )
        for table in profile.tables:
            if table.row_count == 0:
                issues.append(
                    QualityIssue(
                        code="empty_table",
                        severity=QualitySeverity.CRITICAL,
                        message="table contains no rows",
                        table=table.table_name,
                    )
                )
            for column in table.columns:
                if column.null_ratio > 0.5:
                    issues.append(
                        QualityIssue(
                            code="high_null_ratio",
                            severity=QualitySeverity.WARNING,
                            message="column contains more than half null values in the sample",
                            table=table.table_name,
                            column=column.name,
                        )
                    )
                if "identifier" in column.candidate_roles and column.unique_ratio < 1:
                    issues.append(
                        QualityIssue(
                            code="non_unique_identifier",
                            severity=QualitySeverity.CRITICAL,
                            message="identifier candidate is not unique in the sample",
                            table=table.table_name,
                            column=column.name,
                        )
                    )
                if "amount" in column.candidate_roles and any(
                    isinstance(value, (int, float, Decimal)) and value < 0
                    for value in column.sample_values
                    if value is not None
                ):
                    issues.append(
                        QualityIssue(
                            code="negative_amount",
                            severity=QualitySeverity.CRITICAL,
                            message="amount candidate contains a negative value",
                            table=table.table_name,
                            column=column.name,
                        )
                    )
                if "time" in column.candidate_roles and any(
                    (year := _timestamp_year(value)) is not None
                    and not 1970 <= year <= 2100
                    for value in column.sample_values
                    if value is not None
                ):
                    issues.append(
                        QualityIssue(
                            code="invalid_timestamp_range",
                            severity=QualitySeverity.CRITICAL,
                            message="time candidate falls outside the accepted range",
                            table=table.table_name,
                            column=column.name,
                        )
                    )
        return QualityReport(
            passed=not any(issue.severity is QualitySeverity.CRITICAL for issue in issues),
            checked_rows=checked_rows,
            issues=tuple(issues),
        )

    def _column_profile(
        self,
        column_row: dict[str, Any],
        samples: list[dict[str, Any]],
    ) -> ColumnProfile:
        name = column_row["column_name"]
        values = [row.get(name) for row in samples]
        present = [value for value in values if value is not None]
        unique_ratio = len({repr(value) for value in present}) / len(present) if present else 0
        normalized_type = _normalized_type(column_row["data_type"])
        return ColumnProfile(
            name=name,
            normalized_type=normalized_type,
            null_ratio=(values.count(None) / len(values)) if values else 1,
            unique_ratio=unique_ratio,
            sample_values=tuple(_sample_value(value) for value in values[:20]),
            candidate_roles=self._candidate_roles(
                name,
                normalized_type,
                unique_ratio,
            ),
        )

    @staticmethod
    def _candidate_roles(
        name: str,
        normalized_type: str,
        unique_ratio: float,
    ) -> tuple[str, ...]:
        roles: list[str] = []
        lowered = name.casefold()
        if normalized_type in {"numeric", "integer", "float"} and any(
            token in lowered for token in ("amount", "sales", "revenue", "price", "total", "cost")
        ):
            roles.append("amount")
        if normalized_type in {"date", "timestamp", "time"} or any(
            token in lowered for token in ("date", "time", "created", "updated")
        ):
            roles.append("time")
        if lowered == "id" or lowered.endswith("_id") or lowered.endswith("id"):
            roles.append("identifier")
        if normalized_type in {"text", "string"}:
            roles.append("categorical")
        return tuple(dict.fromkeys(roles))


def _validate_staging_schema(schema_name: str) -> None:
    if _STAGING_SCHEMA_PATTERN.fullmatch(schema_name) is None:
        raise UnvalidatedSchemaError(
            "schema profiler only accepts staging_[a-z0-9_]+ schemas"
        )


def _normalized_type(data_type: str) -> str:
    if data_type in _TIME_TYPES:
        return "timestamp" if "timestamp" in data_type else "date"
    if data_type in {"numeric", "decimal"}:
        return "numeric"
    if data_type in {"integer", "bigint", "smallint"}:
        return "integer"
    if data_type in {"real", "double precision"}:
        return "float"
    if data_type in _TEXT_TYPES:
        return "text"
    return data_type.casefold()


def _sample_value(value: Any) -> str | int | float | Decimal | bool | None:
    if value is None or isinstance(value, (str, int, float, Decimal, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _timestamp_year(value: Any) -> int | None:
    if isinstance(value, (date, datetime)):
        return value.year
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).year
        except ValueError:
            return None
    return None
