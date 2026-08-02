from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.metric_retrieval_evaluation import (
    MetricQueryEvaluationSuite,
)
from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever


class VectorDistanceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    query: str
    expected_supported: bool
    expected_metrics: tuple[AnalysisMetric, ...]
    top_metric: AnalysisMetric | None = None
    top_distance: float | None = Field(default=None, ge=0, le=2)
    top_metric_relevant: bool


class DistanceThresholdReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    threshold: float = Field(ge=0, le=2)
    supported_acceptance_rate: float = Field(ge=0, le=1)
    unsupported_rejection_rate: float = Field(ge=0, le=1)
    balanced_accuracy: float = Field(ge=0, le=1)
    observations: tuple[VectorDistanceObservation, ...]


def collect_vector_distance_observations(
    retriever: VectorMetricRetriever,
    suite: MetricQueryEvaluationSuite,
) -> tuple[VectorDistanceObservation, ...]:
    observations: list[VectorDistanceObservation] = []
    for case in suite.cases:
        matches = retriever.search_with_distances(case.query, top_k=1)
        top_match = matches[0] if matches else None
        observations.append(
            VectorDistanceObservation(
                case_id=case.case_id,
                query=case.query,
                expected_supported=bool(case.expected_metrics),
                expected_metrics=case.expected_metrics,
                top_metric=top_match.metric if top_match else None,
                top_distance=top_match.distance if top_match else None,
                top_metric_relevant=(
                    top_match is not None
                    and top_match.metric in case.expected_metrics
                ),
            )
        )
    return tuple(observations)


def select_distance_threshold(
    suite_id: str,
    observations: Sequence[VectorDistanceObservation],
) -> DistanceThresholdReport:
    supported = [item for item in observations if item.expected_supported]
    unsupported = [item for item in observations if not item.expected_supported]
    if not supported or not unsupported:
        raise ValueError(
            "threshold selection requires supported and unsupported cases"
        )

    distances = sorted(
        {
            item.top_distance
            for item in observations
            if item.top_distance is not None
        }
    )
    candidates = [0.0, *distances]
    scored = [
        (
            _balanced_accuracy(supported, unsupported, threshold),
            threshold,
        )
        for threshold in candidates
    ]
    _, threshold = max(scored, key=lambda item: (item[0], -item[1]))
    supported_rate = _acceptance_rate(supported, threshold)
    unsupported_rate = _rejection_rate(unsupported, threshold)
    return DistanceThresholdReport(
        suite_id=suite_id,
        threshold=threshold,
        supported_acceptance_rate=supported_rate,
        unsupported_rejection_rate=unsupported_rate,
        balanced_accuracy=(supported_rate + unsupported_rate) / 2,
        observations=tuple(observations),
    )


def _balanced_accuracy(
    supported: Sequence[VectorDistanceObservation],
    unsupported: Sequence[VectorDistanceObservation],
    threshold: float,
) -> float:
    return (
        _acceptance_rate(supported, threshold)
        + _rejection_rate(unsupported, threshold)
    ) / 2


def _acceptance_rate(
    observations: Sequence[VectorDistanceObservation],
    threshold: float,
) -> float:
    return sum(
        item.top_distance is not None and item.top_distance <= threshold
        for item in observations
    ) / len(observations)


def _rejection_rate(
    observations: Sequence[VectorDistanceObservation],
    threshold: float,
) -> float:
    return sum(
        item.top_distance is None or item.top_distance > threshold
        for item in observations
    ) / len(observations)
