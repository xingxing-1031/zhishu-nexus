from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.models import (
    AnalysisDimension,
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    RetrievalEvidence,
)

_FILTER_SOURCE_COLUMNS = {
    AnalysisFilterField.CHANNEL: "orders.channel",
    AnalysisFilterField.ORDER_STATUS: "orders.status",
    AnalysisFilterField.PRODUCT_ID: "products.product_id",
    AnalysisFilterField.CATEGORY: "products.category",
    AnalysisFilterField.REFUND_STATUS: "refunds.status",
}


class MetricDefinition(BaseModel):
    """Versioned business definition used to ground plan and SQL generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: AnalysisMetric
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    display_name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    source_tables: tuple[str, ...] = Field(min_length=1)
    source_columns: tuple[str, ...] = Field(min_length=1)
    fixed_filters: tuple[AnalysisFilter, ...] = ()
    supported_dimensions: tuple[AnalysisDimension, ...] = ()

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if len(set(self.source_tables)) != len(self.source_tables):
            raise ValueError("source_tables must not contain duplicates")
        if len(set(self.source_columns)) != len(self.source_columns):
            raise ValueError("source_columns must not contain duplicates")
        normalized_aliases = [item.strip().casefold() for item in self.aliases]
        if any(not item for item in normalized_aliases):
            raise ValueError("aliases must not contain empty values")
        if len(set(normalized_aliases)) != len(normalized_aliases):
            raise ValueError("aliases must not contain duplicates")
        if len(set(self.supported_dimensions)) != len(self.supported_dimensions):
            raise ValueError("supported_dimensions must not contain duplicates")
        return self

    @property
    def source_id(self) -> str:
        return f"metric.{self.metric.value}.{self.version}"

    def to_evidence(self) -> RetrievalEvidence:
        filters = ", ".join(
            f"{_FILTER_SOURCE_COLUMNS[item.field]} "
            f"{item.operator.value} {item.value}"
            for item in self.fixed_filters
        ) or "none"
        dimensions = ", ".join(
            item.value for item in self.supported_dimensions
        ) or "none"
        aliases = ", ".join(self.aliases) or "none"
        content = (
            f"{self.display_name} ({self.version}): {self.description}. "
            f"Aliases: {aliases}. "
            f"Formula: {self.formula}. "
            f"Source tables: {', '.join(self.source_tables)}. "
            f"Source columns: {', '.join(self.source_columns)}. "
            f"Fixed filters: {filters}. "
            f"Supported dimensions: {dimensions}."
        )
        return RetrievalEvidence(source_id=self.source_id, content=content)


class MetricCatalog(BaseModel):
    """In-memory catalog for the versioned metric definitions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definitions: tuple[MetricDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_versions(self) -> Self:
        keys = [(item.metric, item.version) for item in self.definitions]
        if len(set(keys)) != len(keys):
            raise ValueError("metric and version pairs must be unique")
        return self

    def get(
        self,
        metric: AnalysisMetric | str,
        *,
        version: str | None = None,
    ) -> MetricDefinition:
        selected_metric = AnalysisMetric(metric)
        matches = [
            item
            for item in self.definitions
            if item.metric is selected_metric
            and (version is None or item.version == version)
        ]
        if not matches:
            suffix = f".{version}" if version else ""
            raise KeyError(
                f"metric definition not found: {selected_metric.value}{suffix}"
            )
        return max(matches, key=lambda item: int(item.version[1:]))


class SchemaColumnDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    nullable: bool = False


class SchemaTableDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    table_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    columns: tuple[SchemaColumnDefinition, ...] = Field(min_length=1)
    primary_key: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_primary_key(self) -> Self:
        column_names = {column.name for column in self.columns}
        missing = set(self.primary_key) - column_names
        if missing:
            raise ValueError(
                f"primary key columns must exist in table: {', '.join(sorted(missing))}"
            )
        return self

    @property
    def source_id(self) -> str:
        return f"schema.{self.table_name}"

    def to_evidence(self) -> RetrievalEvidence:
        columns = "; ".join(
            f"{column.name} ({column.data_type}): {column.description}"
            for column in self.columns
        )
        return RetrievalEvidence(
            source_id=self.source_id,
            content=(
                f"Table {self.table_name}: {self.description}. "
                f"Primary key: {', '.join(self.primary_key)}. "
                f"Columns: {columns}."
            ),
        )


class JoinDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    left_table: str = Field(min_length=1)
    left_column: str = Field(min_length=1)
    right_table: str = Field(min_length=1)
    right_column: str = Field(min_length=1)
    cardinality: Literal["one_to_many", "many_to_one"]
    description: str = Field(min_length=1)

    @property
    def source_id(self) -> str:
        return f"schema.join.{self.left_table}.{self.right_table}"

    def to_evidence(self) -> RetrievalEvidence:
        return RetrievalEvidence(
            source_id=self.source_id,
            content=(
                f"Join {self.left_table}.{self.left_column} = "
                f"{self.right_table}.{self.right_column}; "
                f"cardinality: {self.cardinality}; {self.description}"
            ),
        )


class SchemaCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tables: tuple[SchemaTableDefinition, ...] = Field(min_length=1)
    joins: tuple[JoinDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        table_names = [item.table_name for item in self.tables]
        if len(set(table_names)) != len(table_names):
            raise ValueError("schema table names must be unique")
        known_tables = set(table_names)
        for join in self.joins:
            if {join.left_table, join.right_table} - known_tables:
                raise ValueError("join tables must exist in the schema catalog")
        return self

    def get_table(self, table_name: str) -> SchemaTableDefinition:
        for table in self.tables:
            if table.table_name == table_name:
                return table
        raise KeyError(f"schema table not found: {table_name}")


DEFAULT_METRIC_CATALOG = MetricCatalog(
    definitions=(
        MetricDefinition(
            metric=AnalysisMetric.SALES_AMOUNT,
            version="v1",
            display_name="销售额",
            aliases=("销售额", "销售金额", "成交金额"),
            description="已支付订单中订单明细成交价乘以数量的总和",
            formula="SUM(order_items.quantity * order_items.unit_price)",
            source_tables=("orders", "order_items"),
            source_columns=(
                "orders.status",
                "order_items.quantity",
                "order_items.unit_price",
            ),
            fixed_filters=(
                AnalysisFilter(
                    field=AnalysisFilterField.ORDER_STATUS,
                    operator=AnalysisFilterOperator.EQUALS,
                    value="paid",
                ),
            ),
            supported_dimensions=(
                AnalysisDimension.CHANNEL,
                AnalysisDimension.PRODUCT,
                AnalysisDimension.CATEGORY,
                AnalysisDimension.DAY,
            ),
        ),
        MetricDefinition(
            metric=AnalysisMetric.ORDER_COUNT,
            version="v1",
            display_name="订单数",
            aliases=("订单数", "订单量"),
            description="已支付订单的去重订单数量",
            formula="COUNT(DISTINCT orders.order_id)",
            source_tables=("orders",),
            source_columns=("orders.order_id", "orders.status"),
            fixed_filters=(
                AnalysisFilter(
                    field=AnalysisFilterField.ORDER_STATUS,
                    value="paid",
                ),
            ),
            supported_dimensions=(AnalysisDimension.CHANNEL, AnalysisDimension.DAY),
        ),
        MetricDefinition(
            metric=AnalysisMetric.UNITS_SOLD,
            version="v1",
            display_name="销售件数",
            aliases=(
                "销售件数",
                "销量",
                "最好卖",
                "最畅销",
                "卖得最多",
                "卖得最好",
                "销量最高",
            ),
            description="已支付订单明细中的商品数量总和",
            formula="SUM(order_items.quantity)",
            source_tables=("orders", "order_items"),
            source_columns=("orders.status", "order_items.quantity"),
            fixed_filters=(
                AnalysisFilter(
                    field=AnalysisFilterField.ORDER_STATUS,
                    value="paid",
                ),
            ),
            supported_dimensions=(
                AnalysisDimension.CHANNEL,
                AnalysisDimension.PRODUCT,
                AnalysisDimension.CATEGORY,
                AnalysisDimension.DAY,
            ),
        ),
        MetricDefinition(
            metric=AnalysisMetric.REFUND_AMOUNT,
            version="v1",
            display_name="退款金额",
            aliases=("退款金额",),
            description="退款记录中的退款金额总和，不默认排除任何退款状态",
            formula="SUM(refunds.refund_amount)",
            source_tables=("refunds",),
            source_columns=("refunds.refund_amount", "refunds.status"),
            supported_dimensions=(
                AnalysisDimension.REFUND_STATUS,
                AnalysisDimension.DAY,
            ),
        ),
        MetricDefinition(
            metric=AnalysisMetric.REFUND_COUNT,
            version="v1",
            display_name="退款笔数",
            aliases=("退款笔数", "退款单数"),
            description="退款记录的去重退款编号数量",
            formula="COUNT(DISTINCT refunds.refund_id)",
            source_tables=("refunds",),
            source_columns=("refunds.refund_id", "refunds.status"),
            supported_dimensions=(
                AnalysisDimension.REFUND_STATUS,
                AnalysisDimension.DAY,
            ),
        ),
        MetricDefinition(
            metric=AnalysisMetric.AVERAGE_ORDER_VALUE,
            version="v1",
            display_name="平均订单金额",
            aliases=("平均订单金额", "客单价"),
            description="已支付订单金额除以已支付去重订单数",
            formula=(
                "SUM(orders.amount) / "
                "NULLIF(COUNT(DISTINCT orders.order_id), 0)"
            ),
            source_tables=("orders",),
            source_columns=("orders.amount", "orders.order_id", "orders.status"),
            fixed_filters=(
                AnalysisFilter(
                    field=AnalysisFilterField.ORDER_STATUS,
                    value="paid",
                ),
            ),
            supported_dimensions=(AnalysisDimension.CHANNEL, AnalysisDimension.DAY),
        ),
    )
)


DEFAULT_SCHEMA_CATALOG = SchemaCatalog(
    tables=(
        SchemaTableDefinition(
            table_name="orders",
            description="一次订单及其渠道、金额、状态和创建时间",
            primary_key=("order_id",),
            columns=(
                SchemaColumnDefinition(
                    name="order_id",
                    data_type="TEXT",
                    description="订单唯一编号",
                ),
                SchemaColumnDefinition(
                    name="channel",
                    data_type="TEXT",
                    description="销售渠道",
                ),
                SchemaColumnDefinition(
                    name="amount",
                    data_type="NUMERIC(12,2)",
                    description="订单金额",
                ),
                SchemaColumnDefinition(
                    name="status",
                    data_type="TEXT",
                    description="订单状态",
                ),
                SchemaColumnDefinition(
                    name="created_at",
                    data_type="TIMESTAMPTZ",
                    description="订单创建时间",
                ),
            ),
        ),
        SchemaTableDefinition(
            table_name="products",
            description="商品当前基础信息和参考价格",
            primary_key=("product_id",),
            columns=(
                SchemaColumnDefinition(
                    name="product_id",
                    data_type="TEXT",
                    description="商品唯一编号",
                ),
                SchemaColumnDefinition(
                    name="name",
                    data_type="TEXT",
                    description="商品名称",
                ),
                SchemaColumnDefinition(
                    name="category",
                    data_type="TEXT",
                    description="商品类别",
                ),
                SchemaColumnDefinition(
                    name="unit_price",
                    data_type="NUMERIC(12,2)",
                    description="当前参考价格",
                ),
            ),
        ),
        SchemaTableDefinition(
            table_name="order_items",
            description="订单中的商品明细和成交价快照",
            primary_key=("order_item_id",),
            columns=(
                SchemaColumnDefinition(
                    name="order_item_id",
                    data_type="TEXT",
                    description="订单明细唯一编号",
                ),
                SchemaColumnDefinition(
                    name="order_id",
                    data_type="TEXT",
                    description="关联主订单编号",
                ),
                SchemaColumnDefinition(
                    name="product_id",
                    data_type="TEXT",
                    description="关联商品编号",
                ),
                SchemaColumnDefinition(
                    name="quantity",
                    data_type="INTEGER",
                    description="购买数量",
                ),
                SchemaColumnDefinition(
                    name="unit_price",
                    data_type="NUMERIC(12,2)",
                    description="下单时成交价快照",
                ),
            ),
        ),
        SchemaTableDefinition(
            table_name="refunds",
            description="订单退款事件及其金额、原因和状态",
            primary_key=("refund_id",),
            columns=(
                SchemaColumnDefinition(
                    name="refund_id",
                    data_type="TEXT",
                    description="退款唯一编号",
                ),
                SchemaColumnDefinition(
                    name="order_id",
                    data_type="TEXT",
                    description="关联原订单编号",
                ),
                SchemaColumnDefinition(
                    name="refund_amount",
                    data_type="NUMERIC(12,2)",
                    description="退款金额",
                ),
                SchemaColumnDefinition(
                    name="reason",
                    data_type="TEXT",
                    description="退款原因",
                ),
                SchemaColumnDefinition(
                    name="status",
                    data_type="TEXT",
                    description="退款状态",
                ),
                SchemaColumnDefinition(
                    name="created_at",
                    data_type="TIMESTAMPTZ",
                    description="退款创建时间",
                ),
            ),
        ),
    ),
    joins=(
        JoinDefinition(
            left_table="orders",
            left_column="order_id",
            right_table="order_items",
            right_column="order_id",
            cardinality="one_to_many",
            description="一个订单可以包含多条商品明细",
        ),
        JoinDefinition(
            left_table="products",
            left_column="product_id",
            right_table="order_items",
            right_column="product_id",
            cardinality="one_to_many",
            description="一个商品可以出现在多条订单明细中",
        ),
        JoinDefinition(
            left_table="orders",
            left_column="order_id",
            right_table="refunds",
            right_column="order_id",
            cardinality="one_to_many",
            description="一个订单可以产生多条退款记录",
        ),
    ),
)
