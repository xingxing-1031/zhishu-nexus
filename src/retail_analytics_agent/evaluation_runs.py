from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from statistics import fmean
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationCase,
    BusinessEvaluationSuite,
    EvaluationSplit,
    ExpectedOutcome,
    JsonScalar,
)
from retail_analytics_agent.models import AnalysisPlan, ChartType


class EvaluationVariant(StrEnum):
    BASELINE = "baseline"
    RETRIEVAL = "retrieval"
    RERANKER = "reranker"


def _plans_match(
    actual: AnalysisPlan | None,
    expected: AnalysisPlan,
) -> bool:
    """Compare execution semantics, not the model's paraphrased goal text."""
    if actual is None:
        return False
    return actual.model_dump(exclude={"analysis_goal"}) == expected.model_dump(
        exclude={"analysis_goal"}
    )


class ExperimentConditions(BaseModel):
    """Variables that must remain identical across comparison variants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    dataset_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    split: EvaluationSplit = EvaluationSplit.DEVELOPMENT
    seed_snapshot_id: str = Field(min_length=1)
    reference_time: datetime
    timezone: str = Field(min_length=1)
    safety_policy_version: str = Field(min_length=1)
    access_policy_version: str = Field(min_length=1)
    timeout_ms: int = Field(ge=1)
    model_retry_max_attempts: int = Field(default=3, ge=1, le=5)
    model_retry_initial_backoff_seconds: float = Field(
        default=0.25,
        ge=0,
        le=10,
    )

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        if self.reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        if self.split is not EvaluationSplit.DEVELOPMENT:
            raise ValueError(
                "controlled development experiments must not use holdout"
            )
        return self


class ControlledExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str = Field(min_length=1)
    conditions: ExperimentConditions
    variants: tuple[EvaluationVariant, ...] = Field(min_length=2)
    repetitions: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def validate_variants(self) -> Self:
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("experiment variants must be unique")
        return self


class EvaluationCaseExecutor(Protocol):
    def execute(
        self,
        case: BusinessEvaluationCase,
        *,
        variant: EvaluationVariant,
        run_index: int,
    ) -> EvaluationRunRecord: ...


def ensure_comparable_conditions(
    conditions: tuple[ExperimentConditions, ...],
) -> ExperimentConditions:
    if not conditions:
        raise ValueError("at least one experiment condition is required")
    first = conditions[0]
    if any(item != first for item in conditions[1:]):
        raise ValueError(
            "comparison variants must use identical experiment conditions"
        )
    return first


class EvaluationStage(StrEnum):
    PLAN = "plan"
    EVIDENCE = "evidence"
    SQL = "sql"
    OUTCOME = "outcome"
    ROWS = "rows"
    CHART = "chart"
    ANSWER = "answer"


class EvaluationRunRecord(BaseModel):
    """Immutable raw output captured from one case execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    variant: EvaluationVariant
    run_index: int = Field(ge=1)
    actual_outcome: ExpectedOutcome
    actual_plan: AnalysisPlan | None = None
    actual_source_ids: tuple[str, ...] = ()
    actual_sql: str | None = None
    sql_safe: bool | None = None
    evidence_match: bool | None = None
    scope_rejection_reason: str | None = None
    actual_rows: tuple[dict[str, JsonScalar], ...] = ()
    actual_reason_code: str | None = None
    actual_sensitive_columns: tuple[str, ...] = ()
    actual_chart_type: ChartType | None = None
    answer_correct: bool | None = None
    database_called: bool = False
    final_answer: str | None = None
    latency_ms: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    trace: tuple[str, ...] = ()
    error: str | None = None

    @model_validator(mode="after")
    def validate_run(self) -> Self:
        if len(set(self.actual_source_ids)) != len(self.actual_source_ids):
            raise ValueError("actual_source_ids must not contain duplicates")
        if len(set(self.actual_sensitive_columns)) != len(self.actual_sensitive_columns):
            raise ValueError("actual_sensitive_columns must not contain duplicates")
        if self.actual_sql is not None and not self.actual_sql.strip():
            raise ValueError("actual_sql must not be blank")
        if self.actual_outcome in {
            ExpectedOutcome.REJECTED,
            ExpectedOutcome.APPROVAL_REQUIRED,
        } and self.database_called:
            raise ValueError("rejected or pending runs must not call the database")
        return self


class StageScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: EvaluationStage
    applicable: bool = True
    passed: bool = True
    reason: str = Field(min_length=1)


class EvaluationScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    variant: EvaluationVariant
    run_index: int = Field(ge=1)
    stages: tuple[StageScore, ...] = Field(min_length=1)
    core_result_score: float = Field(ge=0, le=1)
    answer_score: float | None = Field(default=None, ge=0, le=1)
    status: ExpectedOutcome


class VariantSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variant: EvaluationVariant
    run_count: int = Field(ge=1)
    case_count: int = Field(ge=1)
    core_pass_rate: float = Field(ge=0, le=1)
    answer_pass_rate: float | None = Field(default=None, ge=0, le=1)
    stage_pass_rates: dict[EvaluationStage, float]
    average_latency_ms: float = Field(ge=0)
    minimum_latency_ms: int = Field(ge=0)
    maximum_latency_ms: int = Field(ge=0)
    total_retry_count: int = Field(ge=0)


class ExperimentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment: ControlledExperiment
    suite_id: str = Field(min_length=1)
    runs: tuple[EvaluationRunRecord, ...] = Field(min_length=1)
    scores: tuple[EvaluationScore, ...] = Field(min_length=1)
    summaries: tuple[VariantSummary, ...] = Field(min_length=1)


def _stage(
    stage: EvaluationStage,
    passed: bool,
    reason: str,
    *,
    applicable: bool = True,
) -> StageScore:
    return StageScore(
        stage=stage,
        applicable=applicable,
        passed=passed,
        reason=reason,
    )


def _rows_match(
    expected: tuple[dict[str, JsonScalar], ...],
    actual: tuple[dict[str, JsonScalar], ...],
) -> bool:
    if len(expected) != len(actual):
        return False
    for expected_row, actual_row in zip(expected, actual):
        if expected_row.keys() != actual_row.keys():
            return False
        for field in expected_row:
            expected_value = expected_row[field]
            actual_value = actual_row[field]
            numeric_values = (
                isinstance(expected_value, (int, float))
                and not isinstance(expected_value, bool)
            ) or (
                isinstance(actual_value, (int, float))
                and not isinstance(actual_value, bool)
            ) or (
                isinstance(expected_value, str)
                and isinstance(actual_value, str)
                and ("." in expected_value or "." in actual_value)
            )
            if numeric_values:
                try:
                    if Decimal(str(expected_value)) != Decimal(
                        str(actual_value)
                    ):
                        return False
                except InvalidOperation:
                    if expected_value != actual_value:
                        return False
            elif expected_value != actual_value:
                return False
    return True


def score_case(
    case: BusinessEvaluationCase,
    run: EvaluationRunRecord,
) -> EvaluationScore:
    """Score one raw run without invoking a model or a database.

    The core score covers business correctness and security boundaries. The
    answer score is intentionally separate because a summary model can fail
    while the SQL result remains correct.
    """

    if case.case_id != run.case_id:
        raise ValueError("run case_id does not match evaluation case")

    trusted_result = case.expected_outcome in {
        ExpectedOutcome.SUCCEEDED,
        ExpectedOutcome.DEGRADED,
    }
    stages: list[StageScore] = []

    if case.expected_plan is None:
        stages.append(
            _stage(
                EvaluationStage.PLAN,
                True,
                "no plan contract is required for this boundary case",
                applicable=False,
            )
        )
    else:
        plan_matches = _plans_match(run.actual_plan, case.expected_plan)
        stages.append(
            _stage(
                EvaluationStage.PLAN,
                plan_matches,
                "analysis plan matches the human gold business fields"
                if plan_matches
                else "analysis plan differs from the human gold plan",
            )
        )

    if case.expected_source_ids:
        expected_sources = set(case.expected_source_ids)
        actual_sources = set(run.actual_source_ids)
        sources_match = expected_sources == actual_sources
        stages.append(
            _stage(
                EvaluationStage.EVIDENCE,
                sources_match,
                "evidence sources match the minimum sufficient set"
                if sources_match
                else "evidence sources do not match the minimum sufficient set",
            )
        )
    else:
        stages.append(
            _stage(
                EvaluationStage.EVIDENCE,
                True,
                "no evidence contract is required for this boundary case",
                applicable=False,
            )
        )

    if trusted_result or case.expected_outcome is ExpectedOutcome.APPROVAL_REQUIRED:
        sql_passed = (
            run.actual_sql is not None
            and run.sql_safe is True
            and run.evidence_match is True
        )
        sql_reason = (
            "SQL is present, read-only, and consistent with evidence"
            if sql_passed
            else "SQL is missing, unsafe, or inconsistent with evidence"
        )
        stages.append(_stage(EvaluationStage.SQL, sql_passed, sql_reason))
    elif case.expected_outcome is ExpectedOutcome.REJECTED:
        rejected_safely = (
            run.scope_rejection_reason is not None
            or run.sql_safe is False
            or run.evidence_match is False
        ) and not run.database_called
        stages.append(
            _stage(
                EvaluationStage.SQL,
                rejected_safely,
                "unsafe or invalid SQL was rejected before database execution"
                if rejected_safely
                else "rejected request crossed the database boundary",
            )
        )
    else:
        stages.append(
            _stage(
                EvaluationStage.SQL,
                True,
                "SQL stage is not required for this failure contract",
                applicable=False,
            )
        )

    outcome_passed = run.actual_outcome is case.expected_outcome
    if case.expected_reason_code is not None:
        outcome_passed = outcome_passed and (
            run.actual_reason_code == case.expected_reason_code
        )
    if case.expected_sensitive_columns:
        outcome_passed = outcome_passed and (
            set(run.actual_sensitive_columns)
            == set(case.expected_sensitive_columns)
        )
    if case.expected_outcome is ExpectedOutcome.SUCCEEDED:
        # A summarizer failure is degraded, but does not invalidate correct rows.
        outcome_passed = run.actual_outcome in {
            ExpectedOutcome.SUCCEEDED,
            ExpectedOutcome.DEGRADED,
        }
    stages.append(
        _stage(
            EvaluationStage.OUTCOME,
            outcome_passed,
            "outcome is within the expected business boundary"
            if outcome_passed
            else "outcome is outside the expected business boundary",
        )
    )

    rows_required = trusted_result
    rows_passed = (
        run.database_called
        and _rows_match(case.expected_rows, run.actual_rows)
        if rows_required
        else not run.actual_rows
    )
    stages.append(
        _stage(
            EvaluationStage.ROWS,
            rows_passed,
            "database rows exactly match the fixed gold snapshot"
            if rows_passed
            else "database rows do not match the fixed gold snapshot",
            applicable=rows_required or case.expected_outcome is not ExpectedOutcome.APPROVAL_REQUIRED,
        )
    )

    chart_required = case.expected_chart_type is not None and trusted_result
    chart_passed = (
        run.actual_chart_type is case.expected_chart_type
        if chart_required
        else True
    )
    stages.append(
        _stage(
            EvaluationStage.CHART,
            chart_passed,
            "chart type matches the human gold contract"
            if chart_passed
            else "chart type differs from the human gold contract",
            applicable=chart_required,
        )
    )

    answer_applicable = trusted_result
    answer_score = (
        float(run.answer_correct)
        if answer_applicable and run.answer_correct is not None
        else None
    )
    stages.append(
        _stage(
            EvaluationStage.ANSWER,
            run.answer_correct is True,
            "answer was manually judged correct"
            if run.answer_correct is True
            else "answer was not judged correct",
            applicable=answer_applicable and run.answer_correct is not None,
        )
    )

    core_stages = [
        item for item in stages
        if item.applicable and item.stage is not EvaluationStage.ANSWER
    ]
    core_result_score = float(all(item.passed for item in core_stages))
    return EvaluationScore(
        case_id=run.case_id,
        variant=run.variant,
        run_index=run.run_index,
        stages=tuple(stages),
        core_result_score=core_result_score,
        answer_score=answer_score,
        status=run.actual_outcome,
    )


def summarize_variant(
    runs: tuple[EvaluationRunRecord, ...],
    scores: tuple[EvaluationScore, ...],
) -> VariantSummary:
    """Aggregate every run; no best-run selection is allowed."""

    if not runs or not scores:
        raise ValueError("runs and scores must not be empty")
    if len(runs) != len(scores):
        raise ValueError("runs and scores must have the same length")

    variant = runs[0].variant
    if any(run.variant is not variant for run in runs):
        raise ValueError("all runs must use the same variant")
    if any(score.variant is not variant for score in scores):
        raise ValueError("all scores must use the same variant as runs")

    run_keys = [(run.case_id, run.run_index) for run in runs]
    score_keys = [(score.case_id, score.run_index) for score in scores]
    if len(set(run_keys)) != len(run_keys):
        raise ValueError("case_id and run_index pairs must be unique")
    if run_keys != score_keys:
        raise ValueError("run and score identities must match in order")

    answer_scores = [
        score.answer_score
        for score in scores
        if score.answer_score is not None
    ]
    stage_pass_rates: dict[EvaluationStage, float] = {}
    for stage in EvaluationStage:
        applicable = [
            item
            for score in scores
            for item in score.stages
            if item.stage is stage and item.applicable
        ]
        if applicable:
            stage_pass_rates[stage] = fmean(
                float(item.passed) for item in applicable
            )

    latencies = [run.latency_ms for run in runs]
    return VariantSummary(
        variant=variant,
        run_count=len(runs),
        case_count=len({run.case_id for run in runs}),
        core_pass_rate=fmean(score.core_result_score for score in scores),
        answer_pass_rate=(
            fmean(answer_scores) if answer_scores else None
        ),
        stage_pass_rates=stage_pass_rates,
        average_latency_ms=fmean(latencies),
        minimum_latency_ms=min(latencies),
        maximum_latency_ms=max(latencies),
        total_retry_count=sum(run.retry_count for run in runs),
    )


def run_development_experiment(
    experiment: ControlledExperiment,
    suite: BusinessEvaluationSuite,
    executors: dict[EvaluationVariant, EvaluationCaseExecutor],
) -> ExperimentReport:
    """Execute every development case for every variant and repetition."""

    conditions = experiment.conditions
    if suite.split is not EvaluationSplit.DEVELOPMENT or suite.frozen:
        raise ValueError("experiments may only run on an unfrozen development suite")
    if suite.dataset_version != conditions.dataset_version:
        raise ValueError("suite dataset_version does not match experiment conditions")
    if suite.seed_snapshot_id != conditions.seed_snapshot_id:
        raise ValueError("suite snapshot does not match experiment conditions")
    if suite.reference_time != conditions.reference_time:
        raise ValueError("suite reference_time does not match experiment conditions")
    if suite.timezone != conditions.timezone:
        raise ValueError("suite timezone does not match experiment conditions")
    if set(executors) != set(experiment.variants):
        raise ValueError("executors must exactly match experiment variants")

    all_runs: list[EvaluationRunRecord] = []
    all_scores: list[EvaluationScore] = []
    summaries: list[VariantSummary] = []

    for variant in experiment.variants:
        variant_runs: list[EvaluationRunRecord] = []
        variant_scores: list[EvaluationScore] = []
        executor = executors[variant]
        for case in suite.cases:
            for run_index in range(1, experiment.repetitions + 1):
                run = executor.execute(
                    case,
                    variant=variant,
                    run_index=run_index,
                )
                if (
                    run.case_id != case.case_id
                    or run.variant is not variant
                    or run.run_index != run_index
                ):
                    raise ValueError(
                        "executor returned a run with the wrong identity"
                    )
                score = score_case(case, run)
                variant_runs.append(run)
                variant_scores.append(score)

        all_runs.extend(variant_runs)
        all_scores.extend(variant_scores)
        summaries.append(
            summarize_variant(tuple(variant_runs), tuple(variant_scores))
        )

    return ExperimentReport(
        experiment=experiment,
        suite_id=suite.suite_id,
        runs=tuple(all_runs),
        scores=tuple(all_scores),
        summaries=tuple(summaries),
    )
