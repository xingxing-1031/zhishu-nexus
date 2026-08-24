from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from re import fullmatch
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DatasetSourceType(StrEnum):
    POSTGRES = "postgres"
    CSV = "csv"
    PARQUET = "parquet"


class DatasetStatus(StrEnum):
    UPLOADED = "uploaded"
    PROFILING = "profiling"
    NEEDS_MAPPING = "needs_mapping"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DatasetRecord(_StrictModel):
    dataset_id: str = Field(min_length=1, max_length=80)
    dataset_name: str = Field(min_length=1, max_length=200)
    source_type: DatasetSourceType
    source_ref: str | None = Field(default=None, max_length=500)
    schema_name: str = Field(min_length=1, max_length=63)
    version: int = Field(ge=1)
    status: DatasetStatus = DatasetStatus.UPLOADED
    row_count: int = Field(default=0, ge=0)
    quality_report: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("schema_name")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        if fullmatch(r"staging_[a-z0-9_]+", value) is None:
            raise ValueError("schema_name must match staging_[a-z0-9_]+")
        return value


class QualityIssue(_StrictModel):
    code: str = Field(min_length=1, max_length=80)
    severity: QualitySeverity
    message: str = Field(min_length=1, max_length=500)
    table: str = Field(min_length=1, max_length=63)
    column: str | None = Field(default=None, max_length=63)


class QualityReport(_StrictModel):
    passed: bool
    checked_rows: int = Field(ge=0)
    issues: tuple[QualityIssue, ...] = Field(default=(), max_length=100)


class ColumnProfile(_StrictModel):
    name: str = Field(min_length=1, max_length=63)
    normalized_type: str = Field(min_length=1, max_length=80)
    null_ratio: float = Field(ge=0, le=1)
    unique_ratio: float = Field(ge=0, le=1)
    sample_values: tuple[str | int | float | Decimal | bool | None, ...] = Field(
        default=(), max_length=20
    )
    candidate_roles: tuple[str, ...] = Field(default=(), max_length=8)


class TableProfile(_StrictModel):
    table_name: str = Field(min_length=1, max_length=63)
    row_count: int = Field(ge=0)
    columns: tuple[ColumnProfile, ...] = Field(min_length=1, max_length=500)


class SchemaProfile(_StrictModel):
    schema_name: str = Field(min_length=1, max_length=63)
    tables: tuple[TableProfile, ...] = Field(default=(), max_length=200)
