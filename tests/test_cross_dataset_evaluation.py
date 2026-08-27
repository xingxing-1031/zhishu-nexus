"""Deterministic tests for the cross-dataset evaluation contract.

These cover the case schema, the frozen-suite guard, and the scoring and
aggregation functions. They run fully offline: no model or database is
required, so the contract side can be verified without inventing numbers.
"""

from pathlib import Path

from retail_analytics_agent.agent_models import AgentMode
from retail_analytics_agent.cross_dataset_evaluation import (
    CrossDatasetCase,
    CrossDatasetCategory,
    CrossDatasetObservation,
    ExpectedOutcome,
    _score_observation,
    aggregate_cross_dataset_report,
    is_frozen_suite,
    load_cross_dataset_cases,
    score_mapping_fields,
    score_metric_availability,
    score_onboarding,
    score_permission_leakage,
    score_sql_safety,
)
from retail_analytics_agent.models import AccessRole

_EVAL = Path(__file__).resolve().parents[1] / "evaluation"


def _case(**overrides) -> CrossDatasetCase:
    defaults = dict(
        case_id="cs-t-001",
        dataset_id="cross_dataset_sales",
        category=CrossDatasetCategory.BASIC_ANALYSIS,
        question="2025年总销售额是多少",
        access_role=AccessRole.ANALYST,
        expected_outcome=ExpectedOutcome.SUCCEEDED,
        expected_mode=AgentMode.DATA,
        rationale="测试用案例。",
    )
    defaults.update(overrides)
    return CrossDatasetCase(**defaults)


def _obs(**overrides) -> CrossDatasetObservation:
    defaults = dict(
        case_id="cs-t-001",
        dataset_id="cross_dataset_sales",
        category=CrossDatasetCategory.BASIC_ANALYSIS,
        expected_outcome=ExpectedOutcome.SUCCEEDED,
        actual_outcome=ExpectedOutcome.SUCCEEDED,
        actual_mode=AgentMode.DATA,
        latency_ms=10,
    )
    defaults.update(overrides)
    return CrossDatasetObservation(**defaults)


def _lines(name: str) -> list[str]:
    return (_EVAL / name).read_text(encoding="utf-8").splitlines()


class TestSuiteLoading:
    def test_development_suite_loads_and_covers_ten_categories(self) -> None:
        cases = load_cross_dataset_cases(_lines("cross_dataset_development.jsonl"))

        assert len(cases) >= 20
        categories = {case.category for case in cases}
        assert categories == set(CrossDatasetCategory)

    def test_frozen_suite_loads_without_overlap(self) -> None:
        dev = load_cross_dataset_cases(_lines("cross_dataset_development.jsonl"))
        frozen = load_cross_dataset_cases(_lines("cross_dataset_frozen_v2.jsonl"))

        dev_ids = {case.case_id for case in dev}
        frozen_ids = {case.case_id for case in frozen}
        assert len(frozen) >= 10
        assert not (dev_ids & frozen_ids)

    def test_frozen_suite_guard_accepts_frozen_rejects_development(self) -> None:
        dev = load_cross_dataset_cases(_lines("cross_dataset_development.jsonl"))
        frozen = load_cross_dataset_cases(_lines("cross_dataset_frozen_v2.jsonl"))

        assert is_frozen_suite(frozen) is True
        assert is_frozen_suite(dev) is False

    def test_succeeded_cases_require_mode(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            _case(expected_mode=None)

    def test_refused_and_clarification_cases_require_reason_code(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            _case(
                expected_outcome=ExpectedOutcome.REFUSED,
                expected_mode=AgentMode.GENERAL,
                expected_reason_code=None,
            )
        with pytest.raises(ValueError):
            _case(
                expected_outcome=ExpectedOutcome.CLARIFICATION,
                expected_mode=AgentMode.DATA,
                expected_reason_code=None,
            )

    def test_gold_rows_only_for_succeeded(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            _case(
                expected_outcome=ExpectedOutcome.DEGRADED,
                expected_mode=None,
                gold_rows=({"a": 1},),
            )


class TestDeterministicScoring:
    def test_score_onboarding_fraction(self) -> None:
        assert score_onboarding([]) == 0.0
        assert score_onboarding([True, True, True]) == 1.0
        assert score_onboarding([True, False, True]) == round(2 / 3, 4)

    def test_score_mapping_fields_counts_matches(self) -> None:
        gold = {"order_id": "order_no", "amount": "gross_amount"}
        matched, total = score_mapping_fields(
            {"order_id": "order_no", "amount": "gross_amount"},
            gold,
        )
        assert (matched, total) == (2, 2)
        matched, total = score_mapping_fields(
            {"order_id": "order_no", "amount": "sales_amount"},
            gold,
        )
        assert (matched, total) == (1, 2)

    def test_score_metric_availability_fraction(self) -> None:
        assert score_metric_availability([], []) == 1.0
        assert score_metric_availability(
            ["sales_amount", "order_count"],
            ["sales_amount", "order_count", "units_sold"],
        ) == 1.0
        assert score_metric_availability(
            ["sales_amount", "refund_rate"],
            ["sales_amount"],
        ) == 0.5

    def test_score_sql_safety_blocks_unsafe_allows_safe(self) -> None:
        assert score_sql_safety(blocked=False, expected_safe=True) is True
        assert score_sql_safety(blocked=True, expected_safe=False) is True
        assert score_sql_safety(blocked=True, expected_safe=True) is False
        assert score_sql_safety(blocked=False, expected_safe=False) is False

    def test_score_permission_leakage_counts_only_unauthorized_success(self) -> None:
        case = _case(
            case_id="xds",
            category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
            dataset_id="finance",
            expected_outcome=ExpectedOutcome.REFUSED,
            expected_mode=AgentMode.DATA,
            expected_reason_code="dataset_not_found",
        )
        leaked = _obs(
            case_id="xds",
            category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
            expected_outcome=ExpectedOutcome.REFUSED,
            actual_outcome=ExpectedOutcome.SUCCEEDED,
            actual_mode=AgentMode.DATA,
        )
        blocked = _obs(
            case_id="xds",
            category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
            expected_outcome=ExpectedOutcome.REFUSED,
            actual_outcome=ExpectedOutcome.REFUSED,
            actual_mode=AgentMode.DATA,
        )
        del case
        assert score_permission_leakage([leaked, blocked]) == 1


class TestScoreObservation:
    def test_correct_run_passes_every_flag(self) -> None:
        case = _case(
            sql_safe=True,
            expect_data_evidence=True,
            gold_rows=({"result": 1},),
        )
        obs = _obs(sql_blocked=False, data_evidence_present=True, row_count=1)

        scored = _score_observation(obs, case)

        assert scored.outcome_passed is True
        assert scored.route_passed is True
        assert scored.sql_safety_passed is True
        assert scored.clarification_passed is True
        assert scored.refusal_passed is True
        assert scored.evidence_passed is True
        assert scored.result_passed is True

    def test_wrong_outcome_fails_route(self) -> None:
        case = _case(expected_reason_code=None)
        obs = _obs(actual_outcome=ExpectedOutcome.REFUSED, actual_mode=AgentMode.GENERAL)

        scored = _score_observation(obs, case)

        assert scored.outcome_passed is False
        assert scored.route_passed is False

    def test_sql_blocked_on_safe_query_fails_sql_safety(self) -> None:
        case = _case(sql_safe=True)
        obs = _obs(sql_blocked=True)

        scored = _score_observation(obs, case)

        assert scored.sql_safety_passed is False

    def test_clarification_flag_matches_expected(self) -> None:
        case = _case(
            category=CrossDatasetCategory.AMBIGUOUS,
            expected_outcome=ExpectedOutcome.CLARIFICATION,
            expected_reason_code="ambiguous_request",
        )
        obs = _obs(
            category=CrossDatasetCategory.AMBIGUOUS,
            expected_outcome=ExpectedOutcome.CLARIFICATION,
            actual_outcome=ExpectedOutcome.CLARIFICATION,
            actual_mode=AgentMode.DATA,
            clarification_asked=True,
        )

        scored = _score_observation(obs, case)

        assert scored.clarification_passed is True
        assert scored.clarification_asked is True

    def test_refused_case_permits_cross_dataset_access_block(self) -> None:
        case = _case(
            case_id="xds",
            category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
            dataset_id="finance",
            expected_outcome=ExpectedOutcome.REFUSED,
            expected_mode=AgentMode.DATA,
            expected_reason_code="dataset_not_found",
        )
        obs = _obs(
            case_id="xds",
            category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
            expected_outcome=ExpectedOutcome.REFUSED,
            actual_outcome=ExpectedOutcome.REFUSED,
            actual_mode=AgentMode.DATA,
        )

        scored = _score_observation(obs, case)

        assert scored.permission_passed is True
        assert scored.refusal_passed is True


class TestAggregateReport:
    def _suite(self):
        cases = [
            _case(
                case_id="aa",
                expected_metric="sales_amount",
                sql_safe=True,
                expect_data_evidence=True,
                gold_rows=({"result": 1},),
            ),
            _case(
                case_id="bb",
                category=CrossDatasetCategory.UNSAFE_INPUT,
                expected_outcome=ExpectedOutcome.REFUSED,
                expected_mode=AgentMode.GENERAL,
                expected_reason_code="write_operation_refused",
                sql_safe=False,
            ),
            _case(
                case_id="cc",
                category=CrossDatasetCategory.AMBIGUOUS,
                expected_outcome=ExpectedOutcome.CLARIFICATION,
                expected_mode=AgentMode.DATA,
                expected_reason_code="ambiguous_request",
            ),
            _case(
                case_id="dd",
                category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
                dataset_id="finance",
                expected_outcome=ExpectedOutcome.REFUSED,
                expected_mode=AgentMode.DATA,
                expected_reason_code="dataset_not_found",
            ),
        ]
        observations = [
            _obs(
                case_id="aa",
                sql_blocked=False,
                data_evidence_present=True,
                row_count=1,
                latency_ms=100,
            ),
            _obs(
                case_id="bb",
                category=CrossDatasetCategory.UNSAFE_INPUT,
                expected_outcome=ExpectedOutcome.REFUSED,
                actual_outcome=ExpectedOutcome.REFUSED,
                actual_mode=AgentMode.GENERAL,
                sql_blocked=True,
                latency_ms=50,
            ),
            _obs(
                case_id="cc",
                category=CrossDatasetCategory.AMBIGUOUS,
                expected_outcome=ExpectedOutcome.CLARIFICATION,
                actual_outcome=ExpectedOutcome.CLARIFICATION,
                actual_mode=AgentMode.DATA,
                clarification_asked=True,
                latency_ms=30,
            ),
            _obs(
                case_id="dd",
                category=CrossDatasetCategory.CROSS_DATASET_ACCESS,
                expected_outcome=ExpectedOutcome.REFUSED,
                actual_outcome=ExpectedOutcome.REFUSED,
                actual_mode=AgentMode.DATA,
                latency_ms=20,
            ),
        ]
        return cases, observations

    def test_aggregate_perfect_suite(self) -> None:
        cases, observations = self._suite()
        report = aggregate_cross_dataset_report(
            cases,
            observations,
            dataset="cross_dataset_sales",
            split="development",
        )

        assert report.total == 4
        assert report.executed == 4
        assert report.route_accuracy == 1.0
        assert report.clarification_accuracy == 1.0
        assert report.refusal_accuracy == 1.0
        assert report.evidence_accuracy == 1.0
        assert report.metric_availability_accuracy == 1.0
        assert report.sql_safety_pass == 1.0
        assert report.unsafe_sql_block_rate == 1.0
        assert report.sql_execution_success == 1.0
        assert report.business_result_accuracy == 1.0
        assert report.permission_leakage == 0
        assert report.p50_latency_ms == 30
        assert report.p95_latency_ms == 50

    def test_aggregate_counts_execution_and_drops_scores(self) -> None:
        cases, observations = self._suite()
        observations.append(
            _obs(
                case_id="aa",
                actual_outcome=None,
                actual_mode=None,
                error_type="service_error",
                latency_ms=200,
            )
        )
        report = aggregate_cross_dataset_report(
            cases,
            observations,
            dataset="cross_dataset_sales",
            split="development",
        )

        assert report.total == 5
        assert report.executed == 4
        assert report.route_accuracy == 0.8

    def test_aggregate_observations_without_case_raise(self) -> None:
        import pytest

        cases, _observations = self._suite()
        stray = _obs(case_id="nope")
        with pytest.raises(ValueError):
            aggregate_cross_dataset_report(
                cases,
                [stray],
                dataset="cross_dataset_sales",
                split="development",
            )

    def test_report_is_json_serializable(self) -> None:
        cases, observations = self._suite()
        report = aggregate_cross_dataset_report(
            cases,
            observations,
            dataset="cross_dataset_sales",
            split="development",
        )

        dumped = report.model_dump(mode="json")

        assert dumped["suite"] == "cross_dataset"
        assert dumped["dataset"] == "cross_dataset_sales"
        assert isinstance(dumped["records"], list)
        assert len(dumped["records"]) == 4
