from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, field_validator

from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.dataset_models import DatasetSourceType


class UnsafeDatasetPathError(ValueError):
    """Raised when an input file is outside the configured upload root."""


class UnsupportedDatasetFormatError(ValueError):
    """Raised when a declared source type does not match the input file."""


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)
    source_path: Path
    source_type: DatasetSourceType
    target_schema: str = Field(min_length=1, max_length=63)

    @field_validator("target_schema")
    @classmethod
    def validate_target_schema(cls, value: str) -> str:
        if re.fullmatch(r"staging_[a-z0-9_]+", value) is None:
            raise ValueError("target_schema must match staging_[a-z0-9_]+")
        return value


class ImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    version: int
    schema_name: str
    tables: tuple[str, ...]
    row_counts: dict[str, int]


@dataclass(frozen=True)
class FileDatasetImporter:
    upload_root: Path

    def import_file(
        self,
        request: ImportRequest,
        connection: DatabaseConnection,
    ) -> ImportResult:
        source_path = self._safe_source_path(request.source_path)
        self._validate_format(request, source_path)
        rows, columns = self._read_rows(source_path, request.source_type)
        normalized_columns = _normalize_columns(columns)
        column_types = {
            normalized: _infer_column_type(
                [row.get(original) for row in rows]
            )
            for original, normalized in zip(columns, normalized_columns)
        }
        normalized_rows = [
            {
                normalized: _coerce_value(
                    row.get(original),
                    column_types[normalized],
                )
                for original, normalized in zip(columns, normalized_columns)
            }
            for row in rows
        ]

        table_name = "dataset_rows"
        qualified_table = sql.Identifier(request.target_schema, table_name)
        column_definitions = sql.SQL(", ").join(
            sql.SQL("{}").format(sql.Identifier(column))
            + sql.SQL(" ")
            + sql.SQL(column_types[column])
            for column in normalized_columns
        )
        column_identifiers = sql.SQL(", ").join(
            sql.Identifier(column) for column in normalized_columns
        )
        placeholders = sql.SQL(", ").join(
            sql.Placeholder() for _ in normalized_columns
        )

        with connection.transaction():
            connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
                .format(sql.Identifier(request.target_schema))
            )
            connection.execute(
                sql.SQL("CREATE TABLE {} ({})")
                .format(qualified_table, column_definitions)
            )
            if normalized_rows:
                insert_statement = sql.SQL(
                    "INSERT INTO {} ({}) VALUES ({})"
                ).format(qualified_table, column_identifiers, placeholders)
                values = [
                    tuple(row[column] for column in normalized_columns)
                    for row in normalized_rows
                ]
                connection.executemany(insert_statement, values)

        return ImportResult(
            dataset_id=request.dataset_id,
            version=request.version,
            schema_name=request.target_schema,
            tables=(table_name,),
            row_counts={table_name: len(normalized_rows)},
        )

    def _safe_source_path(self, source_path: Path) -> Path:
        root = self.upload_root.expanduser().resolve()
        try:
            resolved = source_path.expanduser().resolve(strict=True)
        except FileNotFoundError as exc:
            raise UnsafeDatasetPathError("dataset file does not exist") from exc
        if not resolved.is_file():
            raise UnsafeDatasetPathError("dataset source must be a regular file")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise UnsafeDatasetPathError(
                "dataset file must be inside the configured upload root"
            ) from exc
        return resolved

    @staticmethod
    def _validate_format(request: ImportRequest, source_path: Path) -> None:
        suffix = source_path.suffix.casefold()
        expected = {
            DatasetSourceType.CSV: ".csv",
            DatasetSourceType.PARQUET: ".parquet",
        }.get(request.source_type)
        if expected is None or suffix != expected:
            raise UnsupportedDatasetFormatError(
                f"{request.source_type.value} import requires a {expected or 'file'} extension"
            )

    @staticmethod
    def _read_rows(
        source_path: Path,
        source_type: DatasetSourceType,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if source_type is DatasetSourceType.CSV:
            with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames
                if not columns or any(not column.strip() for column in columns):
                    raise ValueError("CSV must contain non-empty column names")
                return list(reader), list(columns)

        try:
            import pandas as pd
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "parquet import requires optional data dependencies; "
                "install the 'data' extra"
            ) from exc
        frame = pd.read_parquet(source_path)
        columns = [str(column) for column in frame.columns]
        rows = [
            {
                str(column): _none_for_nan(value)
                for column, value in row.items()
            }
            for row in frame.to_dict(orient="records")
        ]
        return rows, columns


def _normalize_columns(columns: list[str]) -> list[str]:
    normalized: list[str] = []
    for column in columns:
        value = re.sub(r"[^a-zA-Z0-9]+", "_", column).strip("_").lower()
        if not value:
            raise ValueError("column name cannot be normalized to an identifier")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate column names after normalization")
    return normalized


def _infer_column_type(values: list[Any]) -> str:
    present = [value for value in values if value not in (None, "")]
    if not present:
        return "TEXT"
    if all(_as_bool(value) is not None for value in present):
        return "BOOLEAN"
    if all(_as_int(value) is not None for value in present):
        return "BIGINT"
    if all(_as_decimal(value) is not None for value in present):
        return "NUMERIC"
    if all(_as_timestamp(value) is not None for value in present):
        return "TIMESTAMPTZ"
    return "TEXT"


def _coerce_value(value: Any, column_type: str) -> Any:
    if value in (None, ""):
        return None
    if column_type == "BOOLEAN":
        return _as_bool(value)
    if column_type == "BIGINT":
        return _as_int(value)
    if column_type == "NUMERIC":
        return _as_decimal(value)
    if column_type == "TIMESTAMPTZ":
        return _as_timestamp(value)
    return str(value)


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?(0|[1-9]\d*)", value.strip()):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            return None
    return None


def _as_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and ("T" in value or " " in value):
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _none_for_nan(value: Any) -> Any:
    try:
        return None if value != value else value
    except Exception:
        return value


def get_dataset_importer() -> FileDatasetImporter:
    from retail_analytics_agent.settings import get_settings

    return FileDatasetImporter(upload_root=get_settings().dataset_upload_root)
