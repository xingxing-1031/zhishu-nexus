import pytest
from pydantic import ValidationError

from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    DEFAULT_SCHEMA_CATALOG,
    JoinDefinition,
    MetricCatalog,
    MetricDefinition,
    SchemaCatalog,
    SchemaColumnDefinition,
    SchemaTableDefinition,
)
from retail_analytics_agent.models import AnalysisDimension, AnalysisMetric


def test_sales_metric_contains_business_formula_and_source() -> None:
    definition = DEFAULT_METRIC_CATALOG.get(AnalysisMetric.SALES_AMOUNT)

    assert definition.source_id == "metric.sales_amount.v1"
    assert definition.formula == "SUM(order_items.quantity * order_items.unit_price)"
    assert "成交金额" in definition.aliases
    assert "orders.status" in definition.source_columns
    assert definition.fixed_filters[0].value == "paid"
    assert AnalysisDimension.CHANNEL in definition.supported_dimensions

    evidence = definition.to_evidence()
    assert evidence.source_id == "metric.sales_amount.v1"
    assert "paid" in evidence.content
    assert "orders.status equals paid" in evidence.content
    assert "Aliases: 销售额, 销售金额, 成交金额" in evidence.content
    assert "order_items.unit_price" in evidence.content


def test_metric_catalog_returns_latest_version() -> None:
    v1 = DEFAULT_METRIC_CATALOG.get(AnalysisMetric.SALES_AMOUNT)
    v2 = v1.model_copy(
        update={
            "version": "v2",
            "formula": (
                "SUM(order_items.quantity * order_items.unit_price) "
                "- SUM(refunds.refund_amount)"
            ),
        }
    )
    catalog = MetricCatalog(definitions=(*DEFAULT_METRIC_CATALOG.definitions, v2))

    assert catalog.get("sales_amount").version == "v2"
    assert catalog.get("sales_amount", version="v1").formula == v1.formula


def test_refund_rate_metric_has_order_denominator_and_refund_numerator() -> None:
    definition = DEFAULT_METRIC_CATALOG.get(AnalysisMetric.REFUND_RATE)

    assert definition.source_tables == ("orders", "refunds")
    assert "refunds.refund_id" in definition.formula
    assert "orders.order_id" in definition.formula
    assert definition.fixed_filters[0].value == "paid"
    assert AnalysisDimension.CHANNEL in definition.supported_dimensions


def test_metric_catalog_rejects_duplicate_metric_versions() -> None:
    definition = DEFAULT_METRIC_CATALOG.get("sales_amount")

    with pytest.raises(ValidationError, match="metric and version pairs"):
        MetricCatalog(definitions=(definition, definition))


def test_schema_catalog_describes_tables_and_relationships() -> None:
    orders = DEFAULT_SCHEMA_CATALOG.get_table("orders")
    order_items = DEFAULT_SCHEMA_CATALOG.get_table("order_items")

    assert orders.primary_key == ("order_id",)
    assert any(column.name == "created_at" for column in orders.columns)
    assert any(column.name == "unit_price" for column in order_items.columns)
    assert any(
        join.left_table == "orders" and join.right_table == "order_items"
        for join in DEFAULT_SCHEMA_CATALOG.joins
    )
    assert DEFAULT_SCHEMA_CATALOG.joins[0].to_evidence().source_id == (
        "schema.join.orders.order_items"
    )


def test_schema_catalog_rejects_unknown_join_table() -> None:
    table = SchemaTableDefinition(
        table_name="orders",
        description="orders",
        primary_key=("order_id",),
        columns=(
            SchemaColumnDefinition(
                name="order_id",
                data_type="TEXT",
                description="id",
            ),
        ),
    )
    join = JoinDefinition(
        left_table="orders",
        left_column="order_id",
        right_table="missing",
        right_column="id",
        cardinality="one_to_many",
        description="invalid",
    )

    with pytest.raises(ValidationError, match="join tables"):
        SchemaCatalog(tables=(table,), joins=(join,))


def test_metric_definition_rejects_invalid_version_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            metric="sales_amount",
            version="2026-01",
            display_name="销售额",
            description="description",
            formula="SUM(amount)",
            source_tables=("orders",),
            source_columns=("orders.amount",),
            unexpected="not allowed",
        )
