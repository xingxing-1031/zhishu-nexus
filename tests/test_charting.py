import pytest

from retail_analytics_agent.charting import ChartSpecError, build_chart_spec
from retail_analytics_agent.models import AnalysisPlan, ChartType


def test_channel_sales_uses_bar_chart_with_result_fields() -> None:
    plan = AnalysisPlan(
        analysis_goal="最近 30 天各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
    )

    spec = build_chart_spec(
        plan,
        [
            {"channel": "京东", "sales_amount": "11300.00"},
            {"channel": "淘宝", "sales_amount": "9000.00"},
        ],
    )

    assert spec is not None
    assert spec.chart_type is ChartType.BAR
    assert spec.x_field == "channel"
    assert spec.y_fields == ("sales_amount",)


def test_day_dimension_uses_line_chart() -> None:
    plan = AnalysisPlan(
        analysis_goal="每日订单数",
        metrics=["order_count"],
        dimensions=["day"],
    )

    spec = build_chart_spec(
        plan,
        [{"day": "2026-08-01", "order_count": 3}],
    )

    assert spec is not None
    assert spec.chart_type is ChartType.LINE


def test_total_without_dimension_uses_kpi_chart() -> None:
    plan = AnalysisPlan(
        analysis_goal="销售总额",
        metrics=["sales_amount"],
    )

    spec = build_chart_spec(plan, [{"sales_amount": "20300.00"}])

    assert spec is not None
    assert spec.chart_type is ChartType.KPI
    assert spec.x_field is None


def test_empty_rows_do_not_create_a_misleading_chart() -> None:
    plan = AnalysisPlan(
        analysis_goal="各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
    )

    assert build_chart_spec(plan, []) is None


def test_chart_rejects_fields_missing_from_query_rows() -> None:
    plan = AnalysisPlan(
        analysis_goal="各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
    )

    with pytest.raises(ChartSpecError, match="missing metric fields"):
        build_chart_spec(plan, [{"channel": "京东", "profit": "100"}])
