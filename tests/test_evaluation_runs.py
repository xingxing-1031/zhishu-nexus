from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from retail_analytics_agent.business_evaluation import (
    ExpectedOutcome,
    load_business_evaluation_suite,
)
from retail_analytics_agent.evaluation_runs import (
    ControlledExperiment,
    EvaluationRunRecord,
    EvaluationStage,
    EvaluationVariant,
    ExperimentConditions,
    ensure_comparable_conditions,
    run_development_experiment,
    score_case,
    summarize_variant,
)

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def _case(case_id: str):
    suite = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_development.json"
    )
    return next(item for item in suite.cases if item.case_id == case_id)


def _trusted_run(case_id: str, *, outcome: ExpectedOutcome, answer_correct: bool | None = True):
    case = _case(case_id)
    return EvaluationRunRecord(
        case_id=case.case_id,
        variant=EvaluationVariant.BASELINE,
        run_index=1,
        actual_outcome=outcome,
        actual_plan=case.expected_plan,
        actual_source_ids=case.expected_source_ids,
        actual_sql=case.gold_sql,
        sql_safe=True,
        evidence_match=True,
        actual_rows=case.expected_rows,
        actual_chart_type=case.expected_chart_type,
        answer_correct=answer_correct,
        database_called=True,
        final_answer="table result",
        latency_ms=42,
        retry_count=0,
    )


def test_complete_run_has_separate_core_and_answer_scores() -> None:
    case = _case("dev-basic-sales-total")
    score = score_case(
        case,
        _trusted_run(case.case_id, outcome=ExpectedOutcome.SUCCEEDED),
    )

    assert score.core_result_score == 1
    assert score.answer_score == 1
    assert all(item.passed for item in score.stages)


def test_summary_failure_keeps_correct_core_result_as_degraded() -> None:
    case = _case("dev-basic-sales-total")
    score = score_case(
        case,
        _trusted_run(
            case.case_id,
            outcome=ExpectedOutcome.DEGRADED,
            answer_correct=False,
        ),
    )

    assert score.core_result_score == 1
    assert score.answer_score == 0
    assert score.status is ExpectedOutcome.DEGRADED
    answer_stage = next(item for item in score.stages if item.stage is EvaluationStage.ANSWER)
    assert answer_stage.passed is False


def test_read_only_sql_that_violates_evidence_fails_core_score() -> None:
    case = _case("dev-basic-sales-total")
    run = _trusted_run(case.case_id, outcome=ExpectedOutcome.SUCCEEDED)
    run = run.model_copy(update={"evidence_match": False})

    score = score_case(case, run)

    assert score.core_result_score == 0
    sql_stage = next(item for item in score.stages if item.stage is EvaluationStage.SQL)
    assert sql_stage.passed is False


def test_rejected_request_must_match_reason_and_never_call_database() -> None:
    case = next(
        item
        for item in load_business_evaluation_suite(
            EVALUATION_ROOT / "business_development.json"
        ).cases
        if item.expected_outcome is ExpectedOutcome.REJECTED
    )
    run = EvaluationRunRecord(
        case_id=case.case_id,
        variant=EvaluationVariant.RETRIEVAL,
        run_index=2,
        actual_outcome=ExpectedOutcome.REJECTED,
        sql_safe=False,
        actual_reason_code=case.expected_reason_code,
        latency_ms=5,
        retry_count=0,
    )

    score = score_case(case, run)

    assert score.core_result_score == 1
    assert all(item.passed for item in score.stages if item.applicable)


def test_failed_execution_can_have_database_attempt_without_rows() -> None:
    case = next(
        item
        for item in load_business_evaluation_suite(
            EVALUATION_ROOT / "business_development.json"
        ).cases
        if item.expected_outcome is ExpectedOutcome.FAILED
    )
    run = EvaluationRunRecord(
        case_id=case.case_id,
        variant=EvaluationVariant.BASELINE,
        run_index=1,
        actual_outcome=ExpectedOutcome.FAILED,
        actual_reason_code=case.expected_reason_code,
        database_called=True,
        latency_ms=100,
        retry_count=1,
    )

    score = score_case(case, run)

    assert score.core_result_score == 1
    assert next(item for item in score.stages if item.stage is EvaluationStage.ROWS).passed


def test_wrong_rejection_reason_fails_outcome_stage() -> None:
    case = next(
        item
        for item in load_business_evaluation_suite(
            EVALUATION_ROOT / "business_development.json"
        ).cases
        if item.expected_outcome is ExpectedOutcome.REJECTED
    )
    run = EvaluationRunRecord(
        case_id=case.case_id,
        variant=EvaluationVariant.BASELINE,
        run_index=1,
        actual_outcome=ExpectedOutcome.REJECTED,
        sql_safe=False,
        actual_reason_code="wrong_reason",
        latency_ms=5,
        retry_count=0,
    )

    score = score_case(case, run)

    assert score.core_result_score == 0
    assert next(item for item in score.stages if item.stage is EvaluationStage.OUTCOME).passed is False


def test_approval_required_is_validated_but_not_executed() -> None:
    case = next(
        item
        for item in load_business_evaluation_suite(
            EVALUATION_ROOT / "business_development.json"
        ).cases
        if item.expected_outcome is ExpectedOutcome.APPROVAL_REQUIRED
    )
    run = EvaluationRunRecord(
        case_id=case.case_id,
        variant=EvaluationVariant.RERANKER,
        run_index=1,
        actual_outcome=ExpectedOutcome.APPROVAL_REQUIRED,
        actual_plan=case.expected_plan,
        actual_source_ids=case.expected_source_ids,
        actual_sql="SELECT reason FROM refunds",
        sql_safe=True,
        evidence_match=True,
        actual_reason_code=case.expected_reason_code,
        actual_sensitive_columns=case.expected_sensitive_columns,
        latency_ms=10,
        retry_count=0,
    )

    score = score_case(case, run)

    assert score.core_result_score == 1
    assert next(item for item in score.stages if item.stage is EvaluationStage.ROWS).applicable is False


def test_rows_match_equivalent_decimal_string_scales() -> None:
    case = _case("dev-complex-channel-aov")
    run = _trusted_run(
        case.case_id,
        outcome=ExpectedOutcome.SUCCEEDED,
    ).model_copy(
        update={
            "actual_rows": (
                {
                    "channel": "抖音",
                    "average_order_value": "12000.000000",
                },
                {
                    "channel": "京东",
                    "average_order_value": "5650.0000",
                },
                {
                    "channel": "淘宝",
                    "average_order_value": "4800.000",
                },
            ),
        }
    )

    score = score_case(case, run)

    assert next(
        stage for stage in score.stages if stage.stage is EvaluationStage.ROWS
    ).passed is True


def test_rows_match_non_numeric_dotted_strings_strictly() -> None:
    case = _case("dev-basic-sales-total").model_copy(
        update={"expected_rows": ({"version": "v1.0"},)}
    )
    run = _trusted_run(
        case.case_id,
        outcome=ExpectedOutcome.SUCCEEDED,
    ).model_copy(update={"actual_rows": ({"version": "v1.0"},)})

    score = score_case(case, run)

    assert next(
        stage for stage in score.stages if stage.stage is EvaluationStage.ROWS
    ).passed is True


def test_rejected_run_cannot_claim_database_execution() -> None:
    with pytest.raises(ValidationError, match="must not call the database"):
        EvaluationRunRecord(
            case_id="dev-rejected",
            variant=EvaluationVariant.BASELINE,
            run_index=1,
            actual_outcome=ExpectedOutcome.REJECTED,
            database_called=True,
            latency_ms=1,
            retry_count=0,
        )


def test_wrong_chart_type_does_not_pass_core_result() -> None:
    case = _case("dev-basic-sales-total")
    run = _trusted_run(case.case_id, outcome=ExpectedOutcome.SUCCEEDED)
    run = run.model_copy(update={"actual_chart_type": None})

    score = score_case(case, run)

    assert score.core_result_score == 0
    chart_stage = next(
        item for item in score.stages if item.stage is EvaluationStage.CHART
    )
    assert chart_stage.passed is False


def test_run_index_is_preserved_for_repeated_experiments() -> None:
    case = _case("dev-basic-sales-total")
    first = _trusted_run(case.case_id, outcome=ExpectedOutcome.SUCCEEDED)
    second = first.model_copy(update={"run_index": 2, "latency_ms": 80})

    assert first.run_index == 1
    assert second.run_index == 2
    assert second.latency_ms == 80


def test_variant_summary_keeps_all_runs_and_reports_variance() -> None:
    case = _case("dev-basic-sales-total")
    first = _trusted_run(case.case_id, outcome=ExpectedOutcome.SUCCEEDED)
    second = first.model_copy(
        update={
            "run_index": 2,
            "latency_ms": 80,
            "retry_count": 1,
            "evidence_match": False,
            "answer_correct": False,
        }
    )
    scores = (score_case(case, first), score_case(case, second))

    summary = summarize_variant((first, second), scores)

    assert summary.run_count == 2
    assert summary.case_count == 1
    assert summary.core_pass_rate == 0.5
    assert summary.answer_pass_rate == 0.5
    assert summary.stage_pass_rates[EvaluationStage.SQL] == 0.5
    assert summary.average_latency_ms == 61
    assert summary.minimum_latency_ms == 42
    assert summary.maximum_latency_ms == 80
    assert summary.total_retry_count == 1


def test_variant_summary_rejects_duplicate_case_run_identity() -> None:
    case = _case("dev-basic-sales-total")
    run = _trusted_run(case.case_id, outcome=ExpectedOutcome.SUCCEEDED)
    score = score_case(case, run)

    with pytest.raises(ValueError, match="must be unique"):
        summarize_variant((run, run), (score, score))


def _conditions(**updates):
    payload = {
        "model_id": "qwen3:4b",
        "dataset_version": "v1",
        "seed_snapshot_id": "retail-demo-evaluation-2026-08-16-v1",
        "reference_time": datetime.fromisoformat(
            "2026-08-16T12:00:00+08:00"
        ),
        "timezone": "Asia/Shanghai",
        "safety_policy_version": "w5-2",
        "access_policy_version": "w5-1",
        "timeout_ms": 2000,
    }
    payload.update(updates)
    return ExperimentConditions.model_validate(payload)


def test_controlled_experiment_requires_development_and_unique_variants() -> None:
    experiment = ControlledExperiment(
        experiment_id="w6-2-retrieval-ablation",
        conditions=_conditions(),
        variants=(EvaluationVariant.BASELINE, EvaluationVariant.RETRIEVAL),
        repetitions=3,
    )

    assert experiment.conditions.split.value == "development"
    assert experiment.repetitions == 3

    with pytest.raises(ValueError, match="variants must be unique"):
        ControlledExperiment(
            experiment_id="duplicate",
            conditions=_conditions(),
            variants=(EvaluationVariant.BASELINE, EvaluationVariant.BASELINE),
            repetitions=1,
        )


def test_controlled_experiment_rejects_holdout() -> None:
    with pytest.raises(ValueError, match="must not use holdout"):
        _conditions(split="holdout")


def test_comparison_requires_identical_conditions() -> None:
    baseline = _conditions()
    retrieval = _conditions(safety_policy_version="w6-2")

    assert ensure_comparable_conditions((baseline, baseline)) == baseline
    with pytest.raises(ValueError, match="identical experiment conditions"):
        ensure_comparable_conditions((baseline, retrieval))


class _SuccessfulExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, EvaluationVariant, int]] = []

    def execute(self, case, *, variant, run_index):
        self.calls.append((case.case_id, variant, run_index))
        return _trusted_run(
            case.case_id,
            outcome=ExpectedOutcome.SUCCEEDED,
        ).model_copy(
            update={
                "variant": variant,
                "run_index": run_index,
            }
        )


def test_development_runner_keeps_every_variant_and_repetition() -> None:
    development = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_development.json"
    )
    suite = development.model_copy(
        update={"cases": (_case("dev-basic-sales-total"),)}
    )
    experiment = ControlledExperiment(
        experiment_id="w6-2-runner",
        conditions=_conditions(),
        variants=(EvaluationVariant.BASELINE, EvaluationVariant.RETRIEVAL),
        repetitions=2,
    )
    baseline = _SuccessfulExecutor()
    retrieval = _SuccessfulExecutor()

    report = run_development_experiment(
        experiment,
        suite,
        {
            EvaluationVariant.BASELINE: baseline,
            EvaluationVariant.RETRIEVAL: retrieval,
        },
    )

    assert len(report.runs) == 4
    assert len(report.scores) == 4
    assert len(report.summaries) == 2
    assert {summary.core_pass_rate for summary in report.summaries} == {1}
    assert [call[2] for call in baseline.calls] == [1, 2]
    assert [call[2] for call in retrieval.calls] == [1, 2]


def test_development_runner_refuses_frozen_holdout() -> None:
    holdout = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_holdout.json"
    )
    experiment = ControlledExperiment(
        experiment_id="w6-2-holdout-block",
        conditions=_conditions(),
        variants=(EvaluationVariant.BASELINE, EvaluationVariant.RETRIEVAL),
        repetitions=1,
    )

    with pytest.raises(ValueError, match="unfrozen development suite"):
        run_development_experiment(
            experiment,
            holdout,
            {
                EvaluationVariant.BASELINE: _SuccessfulExecutor(),
                EvaluationVariant.RETRIEVAL: _SuccessfulExecutor(),
            },
        )


def test_development_runner_rejects_wrong_executor_identity() -> None:
    development = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_development.json"
    )
    suite = development.model_copy(
        update={"cases": (_case("dev-basic-sales-total"),)}
    )
    experiment = ControlledExperiment(
        experiment_id="w6-2-identity",
        conditions=_conditions(),
        variants=(EvaluationVariant.BASELINE, EvaluationVariant.RETRIEVAL),
        repetitions=1,
    )

    class WrongIdentityExecutor(_SuccessfulExecutor):
        def execute(self, case, *, variant, run_index):
            return super().execute(
                case,
                variant=EvaluationVariant.BASELINE,
                run_index=run_index,
            )

    with pytest.raises(ValueError, match="wrong identity"):
        run_development_experiment(
            experiment,
            suite,
            {
                EvaluationVariant.BASELINE: _SuccessfulExecutor(),
                EvaluationVariant.RETRIEVAL: WrongIdentityExecutor(),
            },
        )
