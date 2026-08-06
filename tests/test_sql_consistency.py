import pytest
from pathlib import Path

from retail_analytics_agent.business_evaluation import (
    ExpectedOutcome,
    load_business_evaluation_suite,
)
from retail_analytics_agent.models import AnalysisPlan
from retail_analytics_agent.sql_consistency import (
    SQLBusinessConsistencyError,
    validate_sql_against_evidence,
)
from retail_analytics_agent.workflow_tools import CatalogRetrievalTool


DEVELOPMENT_SUITE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "business_development.json"
)


def _plan(*, dimensions: list[str] | None = None) -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="最近30天按渠道统计销售额",
        metrics=["sales_amount"],
        dimensions=dimensions or ["channel"],
        time_range={"days": 30},
        limit=10,
    )


def _evidence(plan: AnalysisPlan):
    return CatalogRetrievalTool().retrieve(plan)


def _valid_sql() -> str:
    return (
        "SELECT o.channel, SUM(oi.quantity * oi.unit_price) AS sales_amount "
        "FROM orders AS o JOIN order_items AS oi "
        "ON oi.order_id = o.order_id "
        "WHERE o.status = 'paid' "
        "GROUP BY o.channel"
    )


def test_consistency_accepts_aliases_and_approved_business_shape() -> None:
    result = validate_sql_against_evidence(
        _valid_sql(),
        plan=_plan(),
        evidence=_evidence(_plan()),
    )

    assert result.passed is True
    assert result.reason is None


def test_all_trusted_development_gold_sql_passes_consistency() -> None:
    suite = load_business_evaluation_suite(DEVELOPMENT_SUITE_PATH)
    trusted = {
        ExpectedOutcome.SUCCEEDED,
        ExpectedOutcome.DEGRADED,
    }

    for case in suite.cases:
        if case.expected_outcome not in trusted:
            continue
        assert case.expected_plan is not None
        assert case.gold_sql is not None
        validate_sql_against_evidence(
            case.gold_sql,
            plan=case.expected_plan,
            evidence=_evidence(case.expected_plan),
        )


def test_consistency_rejects_missing_paid_filter() -> None:
    sql = _valid_sql().replace("WHERE o.status = 'paid' ", "")

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="missing_required_filter:orders.status",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )


def test_consistency_rejects_broader_status_filter() -> None:
    sql = _valid_sql().replace(
        "o.status = 'paid'",
        "o.status IN ('paid', 'shipped')",
    )

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="filter_value_mismatch:orders.status",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )


def test_consistency_rejects_missing_approved_join() -> None:
    sql = _valid_sql().replace(
        "JOIN order_items AS oi ON oi.order_id = o.order_id",
        ", order_items AS oi",
    )

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="missing_required_join:schema.join.orders.order_items",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )


def test_consistency_rejects_current_product_price_formula() -> None:
    sql = _valid_sql().replace(
        "oi.quantity * oi.unit_price",
        "oi.quantity * p.unit_price",
    ).replace(
        "FROM orders AS o JOIN order_items AS oi",
        "FROM orders AS o JOIN order_items AS oi "
        "JOIN products AS p ON p.product_id = oi.product_id",
    )

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="sales_formula_must_use_deal_price_times_quantity",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )


def test_consistency_rejects_aggregate_without_dimension_group() -> None:
    sql = _valid_sql().replace(" GROUP BY o.channel", "")

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="dimension_not_grouped:channel",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )


def test_consistency_rejects_metric_alias_drift() -> None:
    sql = _valid_sql().replace("AS sales_amount", "AS refund_amount")

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="missing_metric_alias:sales_amount",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )


def test_consistency_rejects_dimension_alias_drift() -> None:
    sql = _valid_sql().replace("o.channel,", "o.channel AS sales_channel,")

    with pytest.raises(
        SQLBusinessConsistencyError,
        match="missing_dimension_alias:channel",
    ):
        validate_sql_against_evidence(
            sql,
            plan=_plan(),
            evidence=_evidence(_plan()),
        )
