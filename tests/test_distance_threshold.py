from unittest.mock import Mock

import pytest

from retail_analytics_agent.distance_threshold import (
    VectorDistanceObservation,
    collect_vector_distance_observations,
    select_distance_threshold,
)
from retail_analytics_agent.metric_retrieval_evaluation import (
    MetricQueryEvaluationCase,
    MetricQueryEvaluationSuite,
)
from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.vector_metric_retrieval import VectorMetricMatch


def _observation(
    case_id: str,
    *,
    supported: bool,
    distance: float,
) -> VectorDistanceObservation:
    expected = (
        (AnalysisMetric.SALES_AMOUNT,)
        if supported
        else ()
    )
    return VectorDistanceObservation(
        case_id=case_id,
        query=case_id,
        expected_supported=supported,
        expected_metrics=expected,
        top_metric=AnalysisMetric.SALES_AMOUNT,
        top_distance=distance,
        top_metric_relevant=supported,
    )


def test_collect_observations_preserves_labels_and_distances() -> None:
    retriever = Mock()
    retriever.search_with_distances.side_effect = [
        (
            VectorMetricMatch(
                metric=AnalysisMetric.SALES_AMOUNT,
                source_id="metric.sales_amount.v1",
                distance=0.2,
            ),
        ),
        (
            VectorMetricMatch(
                metric=AnalysisMetric.ORDER_COUNT,
                source_id="metric.order_count.v1",
                distance=0.8,
            ),
        ),
    ]
    suite = MetricQueryEvaluationSuite(
        suite_id="validation",
        cases=(
            MetricQueryEvaluationCase(
                case_id="supported",
                query="卖了多少钱",
                expected_metrics=(AnalysisMetric.SALES_AMOUNT,),
            ),
            MetricQueryEvaluationCase(
                case_id="unsupported",
                query="天气",
            ),
        ),
    )

    observations = collect_vector_distance_observations(retriever, suite)

    assert observations[0].top_metric_relevant is True
    assert observations[0].top_distance == 0.2
    assert observations[1].expected_supported is False
    assert observations[1].top_metric_relevant is False


def test_threshold_selection_uses_balanced_accuracy() -> None:
    observations = (
        _observation("supported-1", supported=True, distance=0.2),
        _observation("supported-2", supported=True, distance=0.4),
        _observation("unsupported-1", supported=False, distance=0.7),
        _observation("unsupported-2", supported=False, distance=0.9),
    )

    report = select_distance_threshold("validation", observations)

    assert report.threshold == 0.4
    assert report.supported_acceptance_rate == 1
    assert report.unsupported_rejection_rate == 1
    assert report.balanced_accuracy == 1


def test_threshold_selection_requires_both_classes() -> None:
    observations = (
        _observation("supported", supported=True, distance=0.2),
    )

    with pytest.raises(ValueError, match="supported and unsupported"):
        select_distance_threshold("invalid", observations)
