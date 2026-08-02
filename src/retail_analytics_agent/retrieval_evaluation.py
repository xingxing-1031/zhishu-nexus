from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.models import AnalysisPlan
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalToolError,
    RetrievalTool,
)


class RetrievalEvaluationCase(BaseModel):
    """Human-labelled expected evidence or rejection for one plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    plan: AnalysisPlan
    expected_source_ids: tuple[str, ...] = ()
    expect_rejection: bool = False

    @model_validator(mode="after")
    def validate_expectation(self) -> Self:
        if len(set(self.expected_source_ids)) != len(self.expected_source_ids):
            raise ValueError("expected_source_ids must not contain duplicates")
        if self.expect_rejection and self.expected_source_ids:
            raise ValueError("rejection cases must not contain expected evidence")
        if not self.expect_rejection and not self.expected_source_ids:
            raise ValueError("evidence cases require expected_source_ids")
        return self


class RetrievalEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    cases: tuple[RetrievalEvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case_id values must be unique")
        return self


class RetrievalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    expected_source_ids: tuple[str, ...]
    actual_source_ids: tuple[str, ...]
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    exact_match: bool
    expected_rejection: bool
    actual_rejection: bool
    error: str | None = None


class RetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    case_count: int = Field(ge=1)
    evidence_case_count: int = Field(ge=0)
    rejection_case_count: int = Field(ge=0)
    mean_precision: float = Field(ge=0, le=1)
    mean_recall: float = Field(ge=0, le=1)
    exact_match_rate: float = Field(ge=0, le=1)
    rejection_accuracy: float | None = Field(default=None, ge=0, le=1)
    results: tuple[RetrievalCaseResult, ...]


def load_retrieval_evaluation_suite(
    path: str | Path,
) -> RetrievalEvaluationSuite:
    return RetrievalEvaluationSuite.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def write_retrieval_evaluation_report(
    report: RetrievalEvaluationReport,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def evaluate_retrieval(
    tool: RetrievalTool,
    suite: RetrievalEvaluationSuite,
) -> RetrievalEvaluationReport:
    results = tuple(_evaluate_case(tool, case) for case in suite.cases)
    evidence_results = [item for item in results if not item.expected_rejection]
    rejection_results = [item for item in results if item.expected_rejection]

    return RetrievalEvaluationReport(
        suite_id=suite.suite_id,
        case_count=len(results),
        evidence_case_count=len(evidence_results),
        rejection_case_count=len(rejection_results),
        mean_precision=_mean(
            [item.precision for item in evidence_results if item.precision is not None]
        ),
        mean_recall=_mean(
            [item.recall for item in evidence_results if item.recall is not None]
        ),
        exact_match_rate=_mean([float(item.exact_match) for item in results]),
        rejection_accuracy=(
            _mean([float(item.actual_rejection) for item in rejection_results])
            if rejection_results
            else None
        ),
        results=results,
    )


def _evaluate_case(
    tool: RetrievalTool,
    case: RetrievalEvaluationCase,
) -> RetrievalCaseResult:
    try:
        evidence = tool.retrieve(case.plan)
    except CatalogRetrievalToolError as exc:
        return RetrievalCaseResult(
            case_id=case.case_id,
            expected_source_ids=case.expected_source_ids,
            actual_source_ids=(),
            precision=None if case.expect_rejection else 0.0,
            recall=None if case.expect_rejection else 0.0,
            exact_match=case.expect_rejection,
            expected_rejection=case.expect_rejection,
            actual_rejection=True,
            error=str(exc),
        )

    actual_source_ids = tuple(item.source_id for item in evidence)
    if case.expect_rejection:
        return RetrievalCaseResult(
            case_id=case.case_id,
            expected_source_ids=(),
            actual_source_ids=actual_source_ids,
            exact_match=False,
            expected_rejection=True,
            actual_rejection=False,
        )

    expected = set(case.expected_source_ids)
    actual = set(actual_source_ids)
    correct = expected & actual
    precision = len(correct) / len(actual_source_ids) if actual_source_ids else 0.0
    recall = len(correct) / len(expected)
    return RetrievalCaseResult(
        case_id=case.case_id,
        expected_source_ids=case.expected_source_ids,
        actual_source_ids=actual_source_ids,
        precision=precision,
        recall=recall,
        exact_match=(
            actual == expected and len(actual_source_ids) == len(actual)
        ),
        expected_rejection=False,
        actual_rejection=False,
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
