from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.models import (
    AccessRole,
    AnalysisPlan,
    ChartType,
)

JsonScalar = str | int | float | bool | None


class EvaluationSplit(StrEnum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class EvaluationCategory(StrEnum):
    BASIC_ANALYSIS = "basic_analysis"
    COMPLEX_ANALYSIS = "complex_analysis"
    UNSUPPORTED = "unsupported"
    ACCESS_CONTROL = "access_control"
    RESILIENCE = "resilience"


class ExpectedOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    APPROVAL_REQUIRED = "approval_required"
    DEGRADED = "degraded"
    FAILED = "failed"


class FaultExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str = Field(min_length=1)
    occurrences: tuple[int, ...] = Field(min_length=1)
    error_type: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_occurrences(self) -> Self:
        if any(item < 1 for item in self.occurrences):
            raise ValueError("fault occurrences must be positive")
        if len(set(self.occurrences)) != len(self.occurrences):
            raise ValueError("fault occurrences must not contain duplicates")
        return self


class BusinessEvaluationCase(BaseModel):
    """Human-labelled end-to-end expectation for one business request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    category: EvaluationCategory
    question: str = Field(min_length=1)
    access_role: AccessRole = AccessRole.ANALYST
    expected_outcome: ExpectedOutcome
    expected_plan: AnalysisPlan | None = None
    expected_source_ids: tuple[str, ...] = ()
    gold_sql: str | None = None
    expected_rows: tuple[dict[str, JsonScalar], ...] = ()
    expected_chart_type: ChartType | None = None
    expected_reason_code: str | None = None
    expected_sensitive_columns: tuple[str, ...] = ()
    fault: FaultExpectation | None = None
    rationale: str = Field(min_length=1)
    tags: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        if len(set(self.expected_source_ids)) != len(self.expected_source_ids):
            raise ValueError("expected_source_ids must not contain duplicates")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must not contain duplicates")

        has_trusted_result = self.expected_outcome in {
            ExpectedOutcome.SUCCEEDED,
            ExpectedOutcome.DEGRADED,
        }
        if has_trusted_result:
            if self.expected_plan is None:
                raise ValueError("trusted-result cases require expected_plan")
            if not self.expected_source_ids:
                raise ValueError(
                    "trusted-result cases require expected_source_ids"
                )
            if self.gold_sql is None or not self.gold_sql.strip():
                raise ValueError("trusted-result cases require gold_sql")
        elif self.gold_sql is not None or self.expected_rows:
            raise ValueError(
                "cases without trusted results must not define gold rows"
            )

        if self.expected_rows and self.expected_chart_type is None:
            raise ValueError("non-empty gold rows require expected_chart_type")
        if not self.expected_rows and self.expected_chart_type is not None:
            raise ValueError("empty gold rows must not define a chart type")

        if self.expected_outcome in {
            ExpectedOutcome.REJECTED,
            ExpectedOutcome.FAILED,
        } and not self.expected_reason_code:
            raise ValueError("rejected or failed cases require a reason code")

        if self.expected_outcome is ExpectedOutcome.APPROVAL_REQUIRED:
            if not self.expected_reason_code:
                raise ValueError("approval cases require a reason code")

        if self.category is EvaluationCategory.RESILIENCE:
            if self.fault is None:
                raise ValueError("resilience cases require a fault expectation")
        elif self.fault is not None:
            raise ValueError("only resilience cases may define a fault")
        return self


class BusinessEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    dataset_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    split: EvaluationSplit
    frozen: bool
    reference_time: datetime
    timezone: str = Field(min_length=1)
    seed_snapshot_id: str = Field(min_length=1)
    cases: tuple[BusinessEvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_suite(self) -> Self:
        if self.reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case_id values must be unique")
        if self.split is EvaluationSplit.HOLDOUT and not self.frozen:
            raise ValueError("holdout suites must be frozen")
        if self.split is EvaluationSplit.DEVELOPMENT and self.frozen:
            raise ValueError("development suites must not be frozen")
        return self


def load_business_evaluation_suite(
    path: str | Path,
) -> BusinessEvaluationSuite:
    return BusinessEvaluationSuite.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
