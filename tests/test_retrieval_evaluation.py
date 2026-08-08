from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from retail_analytics_agent.models import RetrievalEvidence
from retail_analytics_agent.retrieval_evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationReport,
    RetrievalEvaluationSuite,
    evaluate_retrieval,
    load_retrieval_evaluation_suite,
    write_retrieval_evaluation_report,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    CatalogRetrievalToolError,
)

GOLD_SUITE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "retrieval_gold.json"
)


def _case(
    *,
    expected_source_ids: tuple[str, ...] = ("source.a",),
    expect_rejection: bool = False,
) -> RetrievalEvaluationCase:
    return RetrievalEvaluationCase(
        case_id="case-1",
        plan={
            "analysis_goal": "统计销售额",
            "metrics": ["sales_amount"],
        },
        expected_source_ids=expected_source_ids,
        expect_rejection=expect_rejection,
    )


def test_evaluation_calculates_precision_recall_and_exact_match() -> None:
    tool = Mock()
    tool.retrieve.return_value = [
        RetrievalEvidence(source_id="source.a", content="a"),
        RetrievalEvidence(source_id="source.b", content="b"),
    ]
    suite = RetrievalEvaluationSuite(
        suite_id="test-suite",
        cases=(_case(expected_source_ids=("source.a", "source.c")),),
    )

    report = evaluate_retrieval(tool, suite)

    assert report.mean_precision == 0.5
    assert report.mean_recall == 0.5
    assert report.exact_match_rate == 0
    assert report.results[0].actual_source_ids == ("source.a", "source.b")


def test_evaluation_marks_expected_rejection_as_exact_match() -> None:
    tool = Mock()
    tool.retrieve.side_effect = CatalogRetrievalToolError("unsupported")
    suite = RetrievalEvaluationSuite(
        suite_id="test-suite",
        cases=(_case(expected_source_ids=(), expect_rejection=True),),
    )

    report = evaluate_retrieval(tool, suite)

    assert report.exact_match_rate == 1
    assert report.rejection_accuracy == 1
    assert report.results[0].actual_rejection is True
    assert report.results[0].error == "unsupported"


def test_evaluation_scores_unexpected_rejection_as_zero() -> None:
    tool = Mock()
    tool.retrieve.side_effect = CatalogRetrievalToolError("unexpected rejection")
    suite = RetrievalEvaluationSuite(
        suite_id="test-suite",
        cases=(_case(),),
    )

    report = evaluate_retrieval(tool, suite)

    assert report.mean_precision == 0
    assert report.mean_recall == 0
    assert report.exact_match_rate == 0
    assert report.results[0].actual_rejection is True


def test_evaluation_penalizes_duplicate_evidence() -> None:
    tool = Mock()
    tool.retrieve.return_value = [
        RetrievalEvidence(source_id="source.a", content="a"),
        RetrievalEvidence(source_id="source.a", content="duplicate a"),
    ]
    suite = RetrievalEvaluationSuite(
        suite_id="test-suite",
        cases=(_case(),),
    )

    report = evaluate_retrieval(tool, suite)

    assert report.mean_precision == 0.5
    assert report.mean_recall == 1
    assert report.exact_match_rate == 0


def test_evaluation_does_not_hide_unexpected_tool_errors() -> None:
    tool = Mock()
    tool.retrieve.side_effect = RuntimeError("programming error")
    suite = RetrievalEvaluationSuite(
        suite_id="test-suite",
        cases=(_case(),),
    )

    with pytest.raises(RuntimeError, match="programming error"):
        evaluate_retrieval(tool, suite)


def test_evaluation_case_rejects_invalid_human_labels() -> None:
    with pytest.raises(ValidationError, match="must not contain expected evidence"):
        _case(expect_rejection=True)

    with pytest.raises(ValidationError, match="require expected_source_ids"):
        _case(expected_source_ids=())


def test_gold_suite_is_human_labelled_and_contains_rejections() -> None:
    suite = load_retrieval_evaluation_suite(GOLD_SUITE_PATH)

    assert suite.suite_id == "catalog-retrieval-v1"
    assert len(suite.cases) == 12
    assert sum(case.expect_rejection for case in suite.cases) == 3
    assert suite.cases[1].expected_source_ids == (
        "metric.sales_amount.v1",
        "schema.orders",
        "schema.products",
        "schema.order_items",
        "schema.join.orders.order_items",
        "schema.join.products.order_items",
    )


def test_catalog_retrieval_baseline_matches_gold_suite() -> None:
    suite = load_retrieval_evaluation_suite(GOLD_SUITE_PATH)

    report = evaluate_retrieval(CatalogRetrievalTool(), suite)

    assert report.case_count == 12
    assert report.evidence_case_count == 9
    assert report.rejection_case_count == 3
    assert report.mean_precision == 1
    assert report.mean_recall == 1
    assert report.exact_match_rate == 1
    assert report.rejection_accuracy == 1


def test_evaluation_report_can_be_saved_as_json(tmp_path: Path) -> None:
    suite = load_retrieval_evaluation_suite(GOLD_SUITE_PATH)
    report = evaluate_retrieval(CatalogRetrievalTool(), suite)
    output_path = tmp_path / "reports" / "baseline.json"

    written_path = write_retrieval_evaluation_report(report, output_path)
    restored = RetrievalEvaluationReport.model_validate_json(
        written_path.read_text(encoding="utf-8")
    )

    assert written_path == output_path
    assert restored == report
