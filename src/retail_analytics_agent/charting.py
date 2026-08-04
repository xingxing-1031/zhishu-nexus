from collections.abc import Sequence

from retail_analytics_agent.models import (
    AnalysisDimension,
    AnalysisPlan,
    ChartSpec,
    ChartType,
)


class ChartSpecError(ValueError):
    """Raised when query rows cannot satisfy the requested chart contract."""


def build_chart_spec(
    plan: AnalysisPlan,
    rows: Sequence[dict[str, object]],
) -> ChartSpec | None:
    if not rows:
        return None

    available_fields = set(rows[0])
    for row in rows[1:]:
        available_fields.intersection_update(row)

    y_fields = tuple(metric.value for metric in plan.metrics)
    missing_metrics = set(y_fields) - available_fields
    if missing_metrics:
        raise ChartSpecError(
            "query rows are missing metric fields: "
            + ", ".join(sorted(missing_metrics))
        )

    if not plan.dimensions:
        return ChartSpec(
            chart_type=ChartType.KPI,
            title=plan.analysis_goal,
            y_fields=y_fields,
        )

    x_field = plan.dimensions[0].value
    if x_field not in available_fields:
        raise ChartSpecError(
            f"query rows are missing dimension field: {x_field}"
        )

    chart_type = (
        ChartType.LINE
        if plan.dimensions[0] is AnalysisDimension.DAY
        else ChartType.BAR
    )
    return ChartSpec(
        chart_type=chart_type,
        title=plan.analysis_goal,
        x_field=x_field,
        y_fields=y_fields,
    )
