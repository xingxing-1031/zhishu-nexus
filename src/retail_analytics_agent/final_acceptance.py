from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationSuite,
    EvaluationSplit,
)
from retail_analytics_agent.evaluation_executors import ObservedWorkflowExecutor
from retail_analytics_agent.evaluation_runs import (
    EvaluationRunRecord,
    EvaluationScore,
    EvaluationVariant,
    VariantSummary,
    score_case,
    summarize_variant,
)


class FinalAcceptanceReport(BaseModel):
    """Immutable evidence from the one-time frozen business acceptance run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_provider: str = Field(min_length=1)
    suite_id: str = Field(min_length=1)
    dataset_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    split: EvaluationSplit
    seed_snapshot_id: str = Field(min_length=1)
    reference_time: datetime
    timezone: str = Field(min_length=1)
    runs: tuple[EvaluationRunRecord, ...] = Field(min_length=1)
    scores: tuple[EvaluationScore, ...] = Field(min_length=1)
    summary: VariantSummary

    @model_validator(mode="after")
    def validate_frozen_report(self) -> "FinalAcceptanceReport":
        if self.split is not EvaluationSplit.HOLDOUT:
            raise ValueError("final acceptance must use the holdout split")
        if len(self.runs) != len(self.scores):
            raise ValueError("every final acceptance run must have one score")
        return self


def run_final_acceptance(
    *,
    execution_id: str,
    model_id: str,
    model_provider: str,
    suite: BusinessEvaluationSuite,
    executor: ObservedWorkflowExecutor,
) -> FinalAcceptanceReport:
    """Run a frozen suite exactly once with the deployed retrieval strategy."""

    if suite.split is not EvaluationSplit.HOLDOUT or not suite.frozen:
        raise ValueError("final acceptance requires a frozen holdout suite")
    if executor.variant is not EvaluationVariant.BASELINE:
        raise ValueError("final acceptance must match the deployed baseline retrieval")

    runs: list[EvaluationRunRecord] = []
    scores: list[EvaluationScore] = []
    for case in suite.cases:
        run = executor.execute(
            case,
            variant=EvaluationVariant.BASELINE,
            run_index=1,
        )
        runs.append(run)
        scores.append(score_case(case, run))

    frozen_runs = tuple(runs)
    frozen_scores = tuple(scores)
    return FinalAcceptanceReport(
        execution_id=execution_id,
        model_id=model_id,
        model_provider=model_provider,
        suite_id=suite.suite_id,
        dataset_version=suite.dataset_version,
        split=suite.split,
        seed_snapshot_id=suite.seed_snapshot_id,
        reference_time=suite.reference_time,
        timezone=suite.timezone,
        runs=frozen_runs,
        scores=frozen_scores,
        summary=summarize_variant(frozen_runs, frozen_scores),
    )
