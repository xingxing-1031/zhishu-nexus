from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from retail_analytics_agent.metric_retrieval import KeywordMetricRetriever
from retail_analytics_agent.metric_retrieval_evaluation import (
    MetricQueryEvaluationCase,
    MetricQueryEvaluationReport,
    MetricQueryEvaluationSuite,
    evaluate_metric_queries,
    load_metric_query_evaluation_suite,
    write_metric_query_evaluation_report,
)
from retail_analytics_agent.models import AnalysisMetric

GOLD_SUITE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "metric_query_gold.json"
)
HOLDOUT_SUITE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "metric_query_holdout.json"
)


def test_query_evaluation_calculates_metrics_and_empty_accuracy() -> None:
    retriever = Mock()
    retriever.search.side_effect = [
        [AnalysisMetric.SALES_AMOUNT, AnalysisMetric.ORDER_COUNT],
        [],
    ]
    suite = MetricQueryEvaluationSuite(
        suite_id="test-suite",
        cases=(
            MetricQueryEvaluationCase(
                case_id="positive",
                query="销售额",
                expected_metrics=(AnalysisMetric.SALES_AMOUNT,),
            ),
            MetricQueryEvaluationCase(
                case_id="empty",
                query="天气",
            ),
        ),
    )

    report = evaluate_metric_queries(retriever, suite, top_k=5)

    assert report.mean_precision_at_k == 0.5
    assert report.mean_recall_at_k == 1
    assert report.exact_match_rate == 0.5
    assert report.empty_query_accuracy == 1


def test_query_evaluation_penalizes_missed_positive_query() -> None:
    retriever = Mock()
    retriever.search.return_value = []
    suite = MetricQueryEvaluationSuite(
        suite_id="test-suite",
        cases=(
            MetricQueryEvaluationCase(
                case_id="miss",
                query="卖了多少钱",
                expected_metrics=(AnalysisMetric.SALES_AMOUNT,),
            ),
        ),
    )

    report = evaluate_metric_queries(retriever, suite)

    assert report.mean_precision_at_k == 0
    assert report.mean_recall_at_k == 0
    assert report.exact_match_rate == 0
    assert report.empty_query_accuracy is None


def test_query_suite_rejects_duplicate_labels_and_case_ids() -> None:
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        MetricQueryEvaluationCase(
            case_id="duplicate",
            query="销售额",
            expected_metrics=(
                AnalysisMetric.SALES_AMOUNT,
                AnalysisMetric.SALES_AMOUNT,
            ),
        )

    case = MetricQueryEvaluationCase(case_id="same", query="天气")
    with pytest.raises(ValidationError, match="case_id values must be unique"):
        MetricQueryEvaluationSuite(
            suite_id="duplicate-suite",
            cases=(case, case),
        )


def test_keyword_baseline_has_intentional_paraphrase_misses() -> None:
    suite = load_metric_query_evaluation_suite(GOLD_SUITE_PATH)

    report = evaluate_metric_queries(KeywordMetricRetriever(), suite, top_k=5)

    assert report.case_count == 11
    assert report.positive_case_count == 10
    assert report.empty_case_count == 1
    assert report.mean_precision_at_k == pytest.approx(0.6)
    assert report.mean_recall_at_k == pytest.approx(0.6)
    assert report.exact_match_rate == pytest.approx(7 / 11)
    assert report.empty_query_accuracy == 1


def test_final_holdout_contains_unseen_positive_and_unsupported_cases() -> None:
    suite = load_metric_query_evaluation_suite(HOLDOUT_SUITE_PATH)

    assert suite.suite_id == "metric-query-final-holdout-v1"
    assert len(suite.cases) == 20
    assert sum(not case.expected_metrics for case in suite.cases) == 8


def test_metric_query_report_can_be_saved(tmp_path: Path) -> None:
    suite = load_metric_query_evaluation_suite(GOLD_SUITE_PATH)
    report = evaluate_metric_queries(KeywordMetricRetriever(), suite)

    output_path = write_metric_query_evaluation_report(
        report,
        tmp_path / "reports" / "keyword.json",
    )
    restored = MetricQueryEvaluationReport.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )

    assert restored == report
