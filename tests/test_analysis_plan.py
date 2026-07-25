from decimal import Decimal

import pytest
from pydantic import ValidationError

from retail_analytics_agent.models import (
    AnalysisDimension,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    SortDirection,
)


def _valid_plan_data() -> dict[str, object]:
    return {
        "analysis_goal": "统计最近30天各渠道已支付订单的销售额",
        "metrics": ["sales_amount"],
        "dimensions": ["channel"],
        "filters": [
            {
                "field": "order_status",
                "operator": "equals",
                "value": "paid",
            }
        ],
        "time_range": {"days": 30},
        "sort": [{"field": "sales_amount", "direction": "descending"}],
        "limit": 10,
    }


def test_analysis_plan_accepts_structured_business_intent() -> None:
    plan = AnalysisPlan.model_validate(_valid_plan_data())

    assert plan.metrics == [AnalysisMetric.SALES_AMOUNT]
    assert plan.dimensions == [AnalysisDimension.CHANNEL]
    assert plan.filters[0].field is AnalysisFilterField.ORDER_STATUS
    assert plan.filters[0].operator is AnalysisFilterOperator.EQUALS
    assert plan.time_range is not None
    assert plan.time_range.days == 30
    assert plan.sort[0].direction is SortDirection.DESCENDING
    assert plan.limit == 10


def test_analysis_plan_rejects_unknown_metric() -> None:
    data = _valid_plan_data()
    data["metrics"] = ["profit"]

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_requires_at_least_one_metric() -> None:
    data = _valid_plan_data()
    data["metrics"] = []

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


@pytest.mark.parametrize("days", [0, 366])
def test_analysis_plan_rejects_time_range_outside_supported_window(
    days: int,
) -> None:
    data = _valid_plan_data()
    data["time_range"] = {"days": days}

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_rejects_unknown_fields() -> None:
    data = _valid_plan_data()
    data["generated_sql"] = "SELECT * FROM orders"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_rejects_list_value_for_equals_filter() -> None:
    data = _valid_plan_data()
    data["filters"] = [
        {
            "field": "channel",
            "operator": "equals",
            "value": ["taobao", "jd"],
        }
    ]

    with pytest.raises(ValidationError, match="requires a scalar value"):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_requires_non_empty_list_for_in_filter() -> None:
    data = _valid_plan_data()
    data["filters"] = [
        {
            "field": "channel",
            "operator": "in",
            "value": [],
        }
    ]

    with pytest.raises(ValidationError, match="requires a non-empty list"):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_accepts_in_filter_with_multiple_values() -> None:
    data = _valid_plan_data()
    data["filters"] = [
        {
            "field": "channel",
            "operator": "in",
            "value": ["taobao", "jd"],
        }
    ]

    plan = AnalysisPlan.model_validate(data)

    assert plan.filters[0].value == ["taobao", "jd"]


def test_analysis_plan_rejects_unselected_sort_field() -> None:
    data = _valid_plan_data()
    data["sort"] = [{"field": "order_count", "direction": "descending"}]

    with pytest.raises(ValidationError, match="sort fields must be selected"):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_rejects_duplicate_metrics() -> None:
    data = _valid_plan_data()
    data["metrics"] = ["sales_amount", "sales_amount"]

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_rejects_duplicate_dimensions() -> None:
    data = _valid_plan_data()
    data["dimensions"] = ["channel", "channel"]

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AnalysisPlan.model_validate(data)


@pytest.mark.parametrize("limit", [0, 1001])
def test_analysis_plan_rejects_limit_outside_supported_range(limit: int) -> None:
    data = _valid_plan_data()
    data["limit"] = limit

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_rejects_unknown_filter_field() -> None:
    data = _valid_plan_data()
    data["filters"] = [
        {
            "field": "customer_phone",
            "operator": "equals",
            "value": "13800000000",
        }
    ]

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


def test_analysis_plan_preserves_numeric_filter_values() -> None:
    data = _valid_plan_data()
    data["filters"] = [
        {
            "field": "product_id",
            "operator": "equals",
            "value": Decimal("1001"),
        }
    ]

    plan = AnalysisPlan.model_validate(data)

    assert plan.filters[0].value == Decimal("1001")
