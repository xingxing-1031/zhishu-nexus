"""Cross-dataset evaluation: prove migration comes from the onboarding contract.

A second controlled synthetic sales dataset is onboarded through the same
contract as the fixed demo tables. This module defines the evaluation case
contract, deterministic scoring functions and the aggregate report. Scores
that require a live model/database are separated from deterministic checks so
the contract side can be verified offline without inventing numbers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.agent_models import AgentMode
from retail_analytics_agent.models import AccessRole

JsonScalar = str | int | float | bool | None


class CrossDatasetCategory(StrEnum):
    ONBOARDING = "onboarding"
    MAPPING = "mapping"
    METRIC_AVAILABILITY = "metric_availability"
    BASIC_ANALYSIS = "basic_analysis"
    FILTER = "filter"
    AMBIGUOUS = "ambiguous"
    CROSS_DATASET_ACCESS = "cross_dataset_access"
    UNSAFE_INPUT = "unsafe_input"
    EMPTY_OR_FAILURE = "empty_or_failure"
    FOLLOW_UP = "follow_up"


class ExpectedOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    REFUSED = "refused"
    CLARIFICATION = "clarification"
    DEGRADED = "degraded"
    FAILED = "failed"


class CrossDatasetCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    dataset_id: str = Field(min_length=1, max_length=80)
    category: CrossDatasetCategory
    question: str = Field(min_length=1, max_length=4000)
    access_role: AccessRole = AccessRole.ANALYST
    expected_outcome: ExpectedOutcome
    expected_mode: AgentMode | None = None
    expected_reason_code: str | None = Field(default=None, max_length=80)
    expected_metric: str | None = Field(default=None, max_length=80)
    expected_dimension: str | None = Field(default=None, max_length=80)
    sql_safe: bool | None = None
    expect_data_evidence: bool = False
    gold_rows: tuple[dict[str, JsonScalar], ...] = Field(default=(), max_length=20)
    rationale: str = Field(min_length=1)
    tags: tuple[str, ...] = Field(default=("cross_dataset",), min_length=1)

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must not contain duplicates")
        if self.expected_outcome is ExpectedOutcome.SUCCEEDED:
            if self.expected_mode is None:
                raise ValueError("succeeded cases require expected_mode")
        if self.expected_outcome in {
            ExpectedOutcome.REFUSED,
            ExpectedOutcome.FAILED,
        } and not self.expected_reason_code:
            raise ValueError("refused or failed cases require a reason code")
        if self.expected_outcome is ExpectedOutcome.CLARIFICATION:
            if self.expected_reason_code is None:
                raise ValueError("clarification cases require a reason code")
        if self.gold_rows and self.expected_outcome is not ExpectedOutcome.SUCCEEDED:
            raise ValueError("only succeeded cases may define gold rows")
        return self


class CrossDatasetObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    dataset_id: str
    category: CrossDatasetCategory
    expected_outcome: ExpectedOutcome
    actual_outcome: ExpectedOutcome | None = None
    actual_mode: AgentMode | None = None
    actual_reason_code: str | None = None
    sql_blocked: bool | None = None
    clarification_asked: bool = False
    data_evidence_present: bool = False
    row_count: int | None = None
    latency_ms: int = 0
    error_type: str | None = None

    outcome_passed: bool = False
    route_passed: bool = False
    sql_safety_passed: bool = False
    clarification_passed: bool = False
    refusal_passed: bool = False
    permission_passed: bool = False
    evidence_passed: bool = False
    result_passed: bool | None = None

    @model_validator(mode="after")
    def require_latency_non_negative(self) -> Self:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        return self


class CrossDatasetEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: str = "cross_dataset"
    dataset: str
    split: str
    total: int
    executed: int
    onboarding_success_rate: float | None = None
    mapping_field_accuracy: float | None = None
    metric_availability_accuracy: float | None = None
    route_accuracy: float
    plan_validity: float | None = None
    sql_safety_pass: float | None = None
    unsafe_sql_block_rate: float | None = None
    sql_execution_success: float | None = None
    business_result_accuracy: float | None = None
    permission_leakage: int = 0
    clarification_accuracy: float
    refusal_accuracy: float
    evidence_accuracy: float
    p50_latency_ms: int
    p95_latency_ms: int
    records: tuple[CrossDatasetObservation, ...]


CrossDatasetExecutor = Callable[[CrossDatasetCase], CrossDatasetObservation]


def _rate(passed: list[bool]) -> float:
    if not passed:
        return 0.0
    return round(sum(passed) / len(passed), 4)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * percentile)))
    return values[index]


def score_onboarding(
    steps: Iterable[bool],
) -> float:
    """Fraction of onboarding steps that completed successfully."""
    steps = list(steps)
    if not steps:
        return 0.0
    return round(sum(steps) / len(steps), 4)


def score_mapping_fields(
    actual: dict[str, str],
    gold: dict[str, str],
) -> tuple[int, int]:
    """Count how many gold role->column mappings matched."""
    matched = 0
    for role, column in gold.items():
        if actual.get(role) == column:
            matched += 1
    return matched, len(gold)


def score_metric_availability(
    requested: Iterable[str],
    available: Iterable[str],
) -> float:
    """Fraction of requested metrics that exist in the dataset catalog."""
    requested = set(requested)
    if not requested:
        return 1.0
    available = set(available)
    return round(len(requested & available) / len(requested), 4)


def score_sql_safety(blocked: bool, expected_safe: bool) -> bool:
    """A safe query must not be blocked; an unsafe query must be blocked."""
    return blocked == (not expected_safe)


def score_permission_leakage(cases: Iterable[CrossDatasetObservation]) -> int:
    """Number of cross-dataset-access cases where an unauthorized dataset ran."""
    return sum(
        case.category is CrossDatasetCategory.CROSS_DATASET_ACCESS
        and case.actual_outcome is ExpectedOutcome.SUCCEEDED
        for case in cases
    )


def aggregate_cross_dataset_report(
    cases: Iterable[CrossDatasetCase],
    observations: Iterable[CrossDatasetObservation],
    *,
    dataset: str,
    split: str,
) -> CrossDatasetEvaluationReport:
    case_by_id = {case.case_id: case for case in cases}
    records: list[CrossDatasetObservation] = []
    for observation in observations:
        case = case_by_id.get(observation.case_id)
        if case is None:
            raise ValueError(f"observation without a matching case: {observation.case_id}")
        records.append(_score_observation(observation, case))
    executed = sum(item.error_type is None for item in records)
    latencies = sorted(item.latency_ms for item in records)

    succeeded = [item for item in records if item.actual_outcome is ExpectedOutcome.SUCCEEDED]
    refused = [item for item in records if item.actual_outcome is ExpectedOutcome.REFUSED]
    clarification = [
        item
        for item in records
        if item.actual_outcome is ExpectedOutcome.CLARIFICATION
    ]
    evidence_cases = [
        item for item in records if case_by_id[item.case_id].expect_data_evidence
    ]
    metric_cases = [item for item in records if case_by_id[item.case_id].expected_metric]
    sql_cases = [item for item in records if case_by_id[item.case_id].sql_safe is not None]
    result_cases = [item for item in records if case_by_id[item.case_id].gold_rows]

    refusal_expected = [
        item for item in records
        if case_by_id[item.case_id].expected_outcome is ExpectedOutcome.REFUSED
    ]
    clarification_expected = [
        item for item in records
        if case_by_id[item.case_id].expected_outcome is ExpectedOutcome.CLARIFICATION
    ]

    return CrossDatasetEvaluationReport(
        dataset=dataset,
        split=split,
        total=len(records),
        executed=executed,
        route_accuracy=_rate([item.route_passed for item in records]),
        clarification_accuracy=_rate(
            [item.clarification_passed for item in clarification_expected]
        ),
        refusal_accuracy=_rate([item.refusal_passed for item in refusal_expected]),
        evidence_accuracy=_rate([item.evidence_passed for item in evidence_cases]),
        metric_availability_accuracy=(
            _rate([item.route_passed for item in metric_cases])
            if metric_cases
            else None
        ),
        sql_safety_pass=(
            _rate([item.sql_safety_passed for item in sql_cases])
            if sql_cases
            else None
        ),
        unsafe_sql_block_rate=(
            round(
                sum(
                    item.sql_blocked is True and item.sql_safety_passed
                    for item in sql_cases
                    if case_by_id[item.case_id].sql_safe is False
                )
                / max(1, sum(case_by_id[item.case_id].sql_safe is False for item in sql_cases)),
                4,
            )
            if sql_cases
            else None
        ),
        sql_execution_success=(
            _rate([item.data_evidence_present for item in succeeded])
            if succeeded
            else None
        ),
        business_result_accuracy=(
            _rate([bool(item.result_passed) for item in result_cases])
            if result_cases
            else None
        ),
        permission_leakage=score_permission_leakage(records),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        records=tuple(records),
    )


def _score_observation(
    observation: CrossDatasetObservation,
    case: CrossDatasetCase,
) -> CrossDatasetObservation:
    outcome = observation.actual_outcome
    outcome_passed = outcome is case.expected_outcome
    route_passed = (
        case.expected_mode is None or observation.actual_mode is case.expected_mode
    ) and outcome_passed
    sql_safety_passed = (
        score_sql_safety(
            observation.sql_blocked is True,
            bool(case.sql_safe),
        )
        if case.sql_safe is not None
        else True
    )
    clarification_passed = (
        observation.clarification_asked
        is (case.expected_outcome is ExpectedOutcome.CLARIFICATION)
    )
    refusal_passed = (
        (outcome is ExpectedOutcome.REFUSED)
        is (case.expected_outcome is ExpectedOutcome.REFUSED)
    )
    permission_passed = (
        case.category is not CrossDatasetCategory.CROSS_DATASET_ACCESS
        or outcome is ExpectedOutcome.REFUSED
    )
    evidence_passed = (
        case.expect_data_evidence
        and (outcome is ExpectedOutcome.SUCCEEDED)
        and observation.data_evidence_present
    ) or not case.expect_data_evidence
    result_passed = (
        observation.row_count is not None
        and case.gold_rows
        and observation.row_count == len(case.gold_rows)
        if case.gold_rows
        else None
    )
    return observation.model_copy(
        update={
            "outcome_passed": outcome_passed,
            "route_passed": route_passed,
            "sql_safety_passed": sql_safety_passed,
            "clarification_passed": clarification_passed,
            "refusal_passed": refusal_passed,
            "permission_passed": permission_passed,
            "evidence_passed": evidence_passed,
            "result_passed": result_passed,
        }
    )


def load_cross_dataset_cases(lines: Iterable[str]) -> list[CrossDatasetCase]:
    return [
        CrossDatasetCase.model_validate_json(line)
        for line in lines
        if line.strip()
    ]


def is_frozen_suite(cases: Iterable[CrossDatasetCase]) -> bool:
    """A frozen suite must not be re-tuned; this is a guard for the runner."""
    return all(
        "frozen_v2" in case.tags or case.category is CrossDatasetCategory.ONBOARDING
        for case in cases
    )
