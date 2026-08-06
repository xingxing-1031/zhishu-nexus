from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field
from sqlglot import parse_one
from sqlglot import exp

from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    DEFAULT_SCHEMA_CATALOG,
    MetricCatalog,
    MetricDefinition,
    SchemaCatalog,
)
from retail_analytics_agent.models import (
    AnalysisDimension,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    RetrievalEvidence,
)
from retail_analytics_agent.sql_safety import SQLSafetyError, validate_read_only_sql


class SQLBusinessConsistencyError(ValueError):
    """Raised when read-only SQL violates the approved business contract."""


class SQLConsistencyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool = True
    checked_metric_source_ids: tuple[str, ...] = ()
    checked_evidence_source_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def reason(self) -> str | None:
        return self.reason_codes[0] if self.reason_codes else None


_FILTER_COLUMNS = {
    AnalysisFilterField.CHANNEL: "orders.channel",
    AnalysisFilterField.ORDER_STATUS: "orders.status",
    AnalysisFilterField.PRODUCT_ID: "products.product_id",
    AnalysisFilterField.CATEGORY: "products.category",
    AnalysisFilterField.REFUND_STATUS: "refunds.status",
}


def validate_sql_against_evidence(
    sql: str,
    *,
    plan: AnalysisPlan,
    evidence: Sequence[RetrievalEvidence],
    metric_catalog: MetricCatalog = DEFAULT_METRIC_CATALOG,
    schema_catalog: SchemaCatalog = DEFAULT_SCHEMA_CATALOG,
) -> SQLConsistencyResult:
    """Validate business structure after SQLGlot's read-only check.

    This first version intentionally checks only deterministic structures that
    can be explained in an audit record. Unsupported or ambiguous structures
    are rejected instead of being treated as equivalent.
    """

    try:
        statement = validate_read_only_sql(sql)
    except SQLSafetyError as exc:
        raise SQLBusinessConsistencyError(f"sql_safety_failed: {exc}") from exc

    evidence_ids = tuple(item.source_id for item in evidence)
    definitions = tuple(_definitions_for_plan(plan, evidence_ids, metric_catalog))
    expected_tables = _evidence_tables(evidence_ids)
    actual_tables, aliases = _tables_and_aliases(statement)
    reasons: list[str] = []

    output_names = _output_names(statement)
    for metric in plan.metrics:
        if metric.value not in output_names:
            reasons.append(f"missing_metric_alias:{metric.value}")
    for dimension in plan.dimensions:
        if dimension.value not in output_names:
            reasons.append(f"missing_dimension_alias:{dimension.value}")

    if not expected_tables:
        reasons.append("missing_schema_evidence")
    missing_tables = expected_tables - actual_tables
    if missing_tables:
        reasons.append(
            "missing_required_tables:" + ",".join(sorted(missing_tables))
        )
    unexpected_tables = actual_tables - expected_tables
    if unexpected_tables:
        reasons.append(
            "unapproved_tables:" + ",".join(sorted(unexpected_tables))
        )

    actual_join_pairs = _join_pairs(statement, aliases)
    for join in schema_catalog.joins:
        if join.source_id not in evidence_ids:
            continue
        expected_pair = frozenset(
            (
                f"{join.left_table}.{join.left_column}",
                f"{join.right_table}.{join.right_column}",
            )
        )
        if expected_pair not in actual_join_pairs:
            reasons.append(f"missing_required_join:{join.source_id}")

    for definition in definitions:
        if definition.metric is AnalysisMetric.SALES_AMOUNT:
            expected_product = frozenset(
                (
                    "order_items.quantity",
                    "order_items.unit_price",
                )
            )
            if expected_product not in _multiplication_pairs(statement, aliases):
                reasons.append("sales_formula_must_use_deal_price_times_quantity")
        elif not _metric_formula_matches(statement, aliases, definition.metric):
            reasons.append(f"metric_formula_mismatch:{definition.source_id}")

        for fixed_filter in definition.fixed_filters:
            reasons.extend(
                _check_filter(
                    statement,
                    aliases,
                    _FILTER_COLUMNS[fixed_filter.field],
                    fixed_filter.operator,
                    fixed_filter.value,
                    required=True,
                )
            )

    for plan_filter in plan.filters:
        reasons.extend(
            _check_filter(
                statement,
                aliases,
                _FILTER_COLUMNS[plan_filter.field],
                plan_filter.operator,
                plan_filter.value,
                required=True,
            )
        )

    if plan.time_range is not None:
        time_column = (
            "refunds.created_at"
            if all("refunds" in item.source_tables for item in definitions)
            else "orders.created_at"
        )
        reasons.extend(_check_time_range(statement, aliases, time_column))

    if plan.dimensions:
        group_columns = _group_columns(statement, aliases)
        for dimension in plan.dimensions:
            dimension_column = _dimension_column(dimension, definitions)
            if dimension_column is None:
                reasons.append(f"unsupported_dimension:{dimension.value}")
            elif dimension is AnalysisDimension.DAY:
                reasons.extend(
                    _check_day_dimension(
                        statement,
                        aliases,
                        dimension_column,
                    )
                )
            elif dimension_column not in group_columns:
                reasons.append(f"dimension_not_grouped:{dimension.value}")

    reasons.extend(_check_sort(statement, plan, definitions))

    if reasons:
        raise SQLBusinessConsistencyError("; ".join(dict.fromkeys(reasons)))

    return SQLConsistencyResult(
        checked_metric_source_ids=tuple(item.source_id for item in definitions),
        checked_evidence_source_ids=evidence_ids,
    )


def _definitions_for_plan(
    plan: AnalysisPlan,
    evidence_ids: Sequence[str],
    catalog: MetricCatalog,
) -> Iterable[MetricDefinition]:
    by_metric = {
        parts[1]: source_id
        for source_id in evidence_ids
        if source_id.startswith("metric.")
        for parts in [source_id.split(".")]
        if len(parts) == 3
    }
    definitions: list[MetricDefinition] = []
    for metric in plan.metrics:
        source_id = by_metric.get(metric.value)
        if source_id is None:
            raise SQLBusinessConsistencyError(
                f"missing_metric_evidence:metric.{metric.value}"
            )
        parts = source_id.split(".")
        if len(parts) != 3:
            raise SQLBusinessConsistencyError(
                f"invalid_metric_source_id:{source_id}"
            )
        definitions.append(catalog.get(metric, version=parts[2]))
    return definitions


def _evidence_tables(source_ids: Sequence[str]) -> set[str]:
    return {
        source_id.removeprefix("schema.")
        for source_id in source_ids
        if source_id.startswith("schema.")
        and not source_id.startswith("schema.join.")
    }


def _tables_and_aliases(
    statement: exp.Expression,
) -> tuple[set[str], dict[str, str]]:
    cte_names = {
        item.alias_or_name.lower()
        for item in statement.find_all(exp.CTE)
        if item.alias_or_name
    }
    tables: set[str] = set()
    aliases: dict[str, str] = {}
    for table in statement.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name in cte_names:
            continue
        tables.add(table_name)
        aliases[table.alias_or_name.lower()] = table_name
    return tables, aliases


def _output_names(statement: exp.Expression) -> set[str]:
    return {
        name.lower()
        for selection in statement.selects
        if (name := selection.alias_or_name)
    }


def _qualified_column(
    column: exp.Column,
    aliases: dict[str, str],
) -> str | None:
    name = column.name.lower()
    qualifier = column.table.lower() if column.table else ""
    if not qualifier:
        return None
    table = aliases.get(qualifier, qualifier)
    return f"{table}.{name}"


def _expression_columns(
    expression: exp.Expression,
    aliases: dict[str, str],
) -> set[str]:
    return {
        qualified
        for column in expression.find_all(exp.Column)
        if (qualified := _qualified_column(column, aliases)) is not None
    }


def _join_pairs(
    statement: exp.Expression,
    aliases: dict[str, str],
) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for join in statement.find_all(exp.Join):
        on_expression = join.args.get("on")
        if on_expression is None:
            continue
        for equality in on_expression.find_all(exp.EQ):
            columns = list(equality.find_all(exp.Column))
            if len(columns) != 2:
                continue
            qualified = [
                _qualified_column(column, aliases) for column in columns
            ]
            if all(item is not None for item in qualified):
                pairs.add(frozenset(qualified))
    return pairs


def _multiplication_pairs(
    statement: exp.Expression,
    aliases: dict[str, str],
) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for multiplication in statement.find_all(exp.Mul):
        columns = list(multiplication.find_all(exp.Column))
        if len(columns) != 2:
            continue
        qualified = [
            _qualified_column(column, aliases) for column in columns
        ]
        if all(item is not None for item in qualified):
            pairs.add(frozenset(qualified))
    return pairs


def _has_sum(
    statement: exp.Expression,
    aliases: dict[str, str],
    column: str,
) -> bool:
    return any(
        column in _expression_columns(item, aliases)
        for item in statement.find_all(exp.Sum)
    )


def _has_distinct_count(
    statement: exp.Expression,
    aliases: dict[str, str],
    column: str,
) -> bool:
    return any(
        item.find(exp.Distinct) is not None
        and column in _expression_columns(item, aliases)
        for item in statement.find_all(exp.Count)
    )


def _metric_formula_matches(
    statement: exp.Expression,
    aliases: dict[str, str],
    metric: AnalysisMetric,
) -> bool:
    if metric is AnalysisMetric.ORDER_COUNT:
        return _has_distinct_count(statement, aliases, "orders.order_id")
    if metric is AnalysisMetric.UNITS_SOLD:
        return _has_sum(statement, aliases, "order_items.quantity")
    if metric is AnalysisMetric.REFUND_AMOUNT:
        return _has_sum(statement, aliases, "refunds.refund_amount")
    if metric is AnalysisMetric.REFUND_COUNT:
        return _has_distinct_count(statement, aliases, "refunds.refund_id")
    if metric is AnalysisMetric.AVERAGE_ORDER_VALUE:
        return (
            statement.find(exp.Div) is not None
            and _has_sum(statement, aliases, "orders.amount")
            and _has_distinct_count(statement, aliases, "orders.order_id")
        )
    return False


def _literal_value(node: exp.Expression) -> str | int | float | None:
    if not isinstance(node, exp.Literal):
        return None
    if node.is_string:
        return str(node.this)
    try:
        return int(node.this)
    except ValueError:
        try:
            return float(node.this)
        except ValueError:
            return None


def _where_predicates(statement: exp.Expression) -> Iterable[exp.Expression]:
    where = statement.args.get("where")
    if where is None:
        return ()
    return (
        node
        for node in where.this.walk()
        if isinstance(node, (exp.EQ, exp.In))
    )


def _check_filter(
    statement: exp.Expression,
    aliases: dict[str, str],
    expected_column: str,
    operator: AnalysisFilterOperator,
    expected_value: object,
    *,
    required: bool,
) -> list[str]:
    actual_values: list[object] = []
    for predicate in _where_predicates(statement):
        if isinstance(predicate, exp.EQ):
            columns = list(predicate.find_all(exp.Column))
            if len(columns) != 1:
                continue
            if _qualified_column(columns[0], aliases) != expected_column:
                continue
            value = _literal_value(predicate.args.get("expression"))
            if value is not None:
                actual_values.append(value)
        elif isinstance(predicate, exp.In):
            column = predicate.this
            if not isinstance(column, exp.Column):
                continue
            if _qualified_column(column, aliases) != expected_column:
                continue
            actual_values.extend(
                value
                for value in (
                    _literal_value(item)
                    for item in predicate.expressions
                )
                if value is not None
            )

    if not actual_values:
        return [f"missing_required_filter:{expected_column}"] if required else []

    expected_values = (
        list(expected_value)
        if operator is AnalysisFilterOperator.IN
        and isinstance(expected_value, list)
        else [expected_value]
    )
    if set(actual_values) != set(expected_values):
        return [
            f"filter_value_mismatch:{expected_column}"
            f":expected={expected_values}:actual={actual_values}"
        ]
    return []


def _check_time_range(
    statement: exp.Expression,
    aliases: dict[str, str],
    expected_column: str,
) -> list[str]:
    has_start = any(
        isinstance(predicate.expression, exp.Placeholder)
        and predicate.expression.this.name == "start_time"
        and isinstance(predicate.this, exp.Column)
        and _qualified_column(predicate.this, aliases) == expected_column
        for predicate in statement.find_all(exp.GTE)
    )
    has_end = any(
        isinstance(predicate.expression, exp.Placeholder)
        and predicate.expression.this.name == "end_time"
        and isinstance(predicate.this, exp.Column)
        and _qualified_column(predicate.this, aliases) == expected_column
        for predicate in statement.find_all(exp.LT)
    )
    reasons: list[str] = []
    if not has_start:
        reasons.append(f"missing_time_lower_bound:{expected_column}")
    if not has_end:
        reasons.append(f"missing_time_upper_bound:{expected_column}")
    return reasons


def _group_columns(
    statement: exp.Expression,
    aliases: dict[str, str],
) -> set[str]:
    group = statement.args.get("group")
    if group is None:
        return set()
    columns = {
        qualified
        for column in group.find_all(exp.Column)
        if (qualified := _qualified_column(column, aliases)) is not None
    }
    projection_aliases = {
        item.alias.lower(): _expression_columns(item.this, aliases)
        for item in statement.find_all(exp.Alias)
        if item.alias
    }
    for column in group.find_all(exp.Column):
        if column.table:
            continue
        columns.update(projection_aliases.get(column.name.lower(), set()))
    return columns


def _check_day_dimension(
    statement: exp.Expression,
    aliases: dict[str, str],
    expected_column: str,
) -> list[str]:
    """Require the approved timezone-aware natural-day grouping expression."""

    day_projection = next(
        (
            selection.this
            for selection in statement.selects
            if selection.alias_or_name.casefold() == "day"
            and isinstance(selection, exp.Alias)
        ),
        None,
    )
    reasons: list[str] = []
    if day_projection is None or not _is_business_day_expression(
        day_projection, aliases, expected_column
    ):
        reasons.append("day_dimension_must_use_business_timezone")

    group = statement.args.get("group")
    grouped_natural_day = False
    if group is not None:
        for item in group.expressions:
            if (
                isinstance(item, exp.Column)
                and not item.table
                and item.name.casefold() == "day"
            ) or _is_business_day_expression(item, aliases, expected_column):
                grouped_natural_day = True
                break
    if not grouped_natural_day:
        reasons.append("day_dimension_not_grouped_by_natural_day")
    return reasons


def _is_business_day_expression(
    expression: exp.Expression,
    aliases: dict[str, str],
    expected_column: str,
) -> bool:
    columns = _expression_columns(expression, aliases)
    if expected_column not in columns:
        return False

    has_shanghai_timezone = any(
        isinstance(node, exp.AtTimeZone)
        and isinstance(node.args.get("zone"), exp.Literal)
        and node.args["zone"].is_string
        and str(node.args["zone"].this).casefold() == "asia/shanghai"
        for node in expression.find_all(exp.AtTimeZone)
    )
    has_date_cast = any(
        isinstance(node, exp.Cast)
        and isinstance(node.args.get("to"), exp.DataType)
        and node.args["to"].this is exp.DataType.Type.DATE
        for node in expression.find_all(exp.Cast)
    ) or expression.find(exp.Date) is not None
    return has_shanghai_timezone and has_date_cast


def _check_sort(
    statement: exp.Expression,
    plan: AnalysisPlan,
    definitions: Sequence[MetricDefinition],
) -> list[str]:
    if not plan.sort:
        return []
    order = statement.args.get("order")
    if order is None:
        return [
            f"missing_required_sort:{item.field.value}"
            for item in plan.sort
        ]

    actual: dict[str, bool] = {}
    for item in order.expressions:
        if not isinstance(item, exp.Ordered):
            continue
        expression = item.this
        if isinstance(expression, exp.Column) and not expression.table:
            key = expression.name.lower()
        else:
            key = expression.sql(dialect="postgres").casefold()
        actual[key] = bool(item.args.get("desc"))

    reasons: list[str] = []
    for item in plan.sort:
        field = item.field.value
        definition = next(
            (item for item in definitions if item.metric.value == field),
            None,
        )
        accepted_keys = {field}
        if definition is not None:
            accepted_keys.add(
                parse_one(definition.formula, dialect="postgres")
                .sql(dialect="postgres")
                .casefold()
            )
        actual_key = next(
            (key for key in accepted_keys if key in actual),
            None,
        )
        if actual_key is None:
            reasons.append(f"missing_required_sort:{field}")
            continue
        expected_descending = item.direction.value == "descending"
        if actual[actual_key] is not expected_descending:
            reasons.append(f"sort_direction_mismatch:{field}")
    return reasons


def _dimension_column(
    dimension: AnalysisDimension,
    definitions: Sequence[MetricDefinition],
) -> str | None:
    if dimension is AnalysisDimension.DAY:
        if all("refunds" in item.source_tables for item in definitions):
            return "refunds.created_at"
        return "orders.created_at"
    return {
        AnalysisDimension.CHANNEL: "orders.channel",
        AnalysisDimension.PRODUCT: "products.name",
        AnalysisDimension.CATEGORY: "products.category",
        AnalysisDimension.ORDER_STATUS: "orders.status",
        AnalysisDimension.REFUND_STATUS: "refunds.status",
    }.get(dimension)
