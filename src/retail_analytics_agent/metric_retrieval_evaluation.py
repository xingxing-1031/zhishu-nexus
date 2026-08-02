from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.metric_retrieval import MetricRetriever


class MetricQueryEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected_metrics: tuple[AnalysisMetric, ...] = ()

    @model_validator(mode="after")
    def validate_unique_metrics(self) -> Self:
        if len(set(self.expected_metrics)) != len(self.expected_metrics):
            raise ValueError("expected_metrics must not contain duplicates")
        return self


class MetricQueryEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    cases: tuple[MetricQueryEvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case_id values must be unique")
        return self


class MetricQueryCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    query: str
    expected_metrics: tuple[AnalysisMetric, ...]
    actual_metrics: tuple[AnalysisMetric, ...]
    precision_at_k: float | None = Field(default=None, ge=0, le=1)
    recall_at_k: float | None = Field(default=None, ge=0, le=1)
    exact_match: bool


class MetricQueryEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    top_k: int = Field(ge=1)
    case_count: int = Field(ge=1)
    positive_case_count: int = Field(ge=0)
    empty_case_count: int = Field(ge=0)
    mean_precision_at_k: float = Field(ge=0, le=1)
    mean_recall_at_k: float = Field(ge=0, le=1)
    exact_match_rate: float = Field(ge=0, le=1)
    empty_query_accuracy: float | None = Field(default=None, ge=0, le=1)
    results: tuple[MetricQueryCaseResult, ...]


def load_metric_query_evaluation_suite(
    path: str | Path,
) -> MetricQueryEvaluationSuite:
    return MetricQueryEvaluationSuite.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def write_metric_query_evaluation_report(
    report: MetricQueryEvaluationReport,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def evaluate_metric_queries(
    retriever: MetricRetriever,
    suite: MetricQueryEvaluationSuite,
    *,
    top_k: int = 5,
) -> MetricQueryEvaluationReport:
    results = tuple(
        _evaluate_case(retriever, case, top_k=top_k)
        for case in suite.cases
    )
    positive_results = [item for item in results if item.expected_metrics]
    empty_results = [item for item in results if not item.expected_metrics]
    return MetricQueryEvaluationReport(
        suite_id=suite.suite_id,
        top_k=top_k,
        case_count=len(results),
        positive_case_count=len(positive_results),
        empty_case_count=len(empty_results),
        mean_precision_at_k=_mean(
            [
                item.precision_at_k
                for item in positive_results
                if item.precision_at_k is not None
            ]
        ),
        mean_recall_at_k=_mean(
            [
                item.recall_at_k
                for item in positive_results
                if item.recall_at_k is not None
            ]
        ),
        exact_match_rate=_mean([float(item.exact_match) for item in results]),
        empty_query_accuracy=(
            _mean([float(not item.actual_metrics) for item in empty_results])
            if empty_results
            else None
        ),
        results=results,
    )


def _evaluate_case(
    retriever: MetricRetriever,
    case: MetricQueryEvaluationCase,
    *,
    top_k: int,
) -> MetricQueryCaseResult:
    actual_metrics = tuple(retriever.search(case.query, top_k=top_k))
    actual_top_k = actual_metrics[:top_k]
    expected = set(case.expected_metrics)
    actual = set(actual_top_k)

    if not expected:
        return MetricQueryCaseResult(
            case_id=case.case_id,
            query=case.query,
            expected_metrics=(),
            actual_metrics=actual_top_k,
            exact_match=not actual_top_k,
        )

    correct = expected & actual
    return MetricQueryCaseResult(
        case_id=case.case_id,
        query=case.query,
        expected_metrics=case.expected_metrics,
        actual_metrics=actual_top_k,
        precision_at_k=(
            len(correct) / len(actual_top_k) if actual_top_k else 0.0
        ),
        recall_at_k=len(correct) / len(expected),
        exact_match=(
            actual == expected and len(actual_top_k) == len(actual)
        ),
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
