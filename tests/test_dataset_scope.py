"""阶段2核心测试：数据集分析范围解析、跨数据集隔离与服务端拒答。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from retail_analytics_agent.analysis_service import _PUBLIC_REJECTION_MESSAGES
from retail_analytics_agent.audit import QueryAuditStatus
from retail_analytics_agent.dataset_mapping import (
    DatasetMapping,
    MappingField,
    MappingRole,
)
from retail_analytics_agent.dataset_models import (
    ColumnProfile,
    DatasetRecord,
    DatasetSourceType,
    DatasetStatus,
    SchemaProfile,
    TableProfile,
)
from retail_analytics_agent.dataset_scope import (
    DatasetScope,
    DatasetScopeRejectionError,
    DatasetScopeResolver,
    resolve_dataset_scope,
)
from retail_analytics_agent.metric_models import (
    DatasetMetric,
    MetricStatus,
)
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisDimension,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisRequest,
)
from retail_analytics_agent.model_adapters import _sql_generation_contract
from retail_analytics_agent.sql_safety import SQLSafetyError, prepare_safe_sql
from retail_analytics_agent.workflow import (
    build_analysis_graph,
    create_domain_scope_node,
    create_initial_state,
    create_workflow_nodes,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    SQLConsistencyValidationTool,
    SQLGlotValidationTool,
    SQLValidationToolError,
)


def _column(name: str, column_type: str, roles: tuple[str, ...]) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        normalized_type=column_type,
        null_ratio=0,
        unique_ratio=0.5,
        candidate_roles=roles,
    )


def _profile(schema_name: str, columns: tuple[ColumnProfile, ...]) -> SchemaProfile:
    return SchemaProfile(
        schema_name=schema_name,
        tables=(
            TableProfile(
                table_name="dataset_rows",
                row_count=2,
                columns=columns,
            ),
        ),
    )


def _record(
    dataset_id: str,
    version: int,
    schema_name: str,
    *,
    status: DatasetStatus = DatasetStatus.READY,
    mapping_confirmed: bool = True,
) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        dataset_name=f"数据集 {dataset_id}",
        source_type=DatasetSourceType.CSV,
        source_ref=f"uploads/{dataset_id}.csv",
        schema_name=schema_name,
        version=version,
        status=status,
        row_count=2,
        mapping_confirmed=mapping_confirmed,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        updated_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def _mapping(
    dataset_id: str,
    version: int,
    fields: tuple[tuple[MappingRole, str], ...],
    *,
    confirmed: bool = True,
) -> DatasetMapping:
    return DatasetMapping(
        dataset_id=dataset_id,
        version=version,
        fields=tuple(
            MappingField(
                role=role,
                table="dataset_rows",
                column=column,
                confidence=0.9,
            )
            for role, column in fields
        ),
        confirmed=confirmed,
    )


def _metric(
    dataset_id: str,
    version: int,
    formula: str,
    source_column: str,
    *,
    dimensions: tuple[MappingRole, ...] = (),
    metric_id: str = "sales_amount",
    status: MetricStatus = MetricStatus.CONFIRMED,
) -> DatasetMetric:
    return DatasetMetric(
        dataset_id=dataset_id,
        dataset_version=version,
        metric_id=metric_id,
        metric_version="v1",
        name="销售额",
        definition="销售额为已确认金额字段的合计。",
        aggregation="SUM",
        formula=formula,
        source_role=MappingRole.AMOUNT,
        source_table="dataset_rows",
        source_column=source_column,
        supported_dimensions=dimensions,
        status=status,
    )


_DATASET_A_COLUMNS = (
    _column("order_id", "string", ("identifier",)),
    _column("total_amount", "numeric", ("amount",)),
    _column("sales_channel", "string", ("category",)),
    _column("ordered_at", "datetime", ("time",)),
)

_DATASET_B_COLUMNS = (
    _column("txn_no", "string", ("identifier",)),
    _column("revenue", "numeric", ("amount",)),
    _column("source", "string", ("category",)),
    _column("transaction_date", "datetime", ("time",)),
)


def _scope_a() -> DatasetScope:
    record = _record("alpha", 1, "staging_alpha_1")
    mapping = _mapping(
        "alpha",
        1,
        (
            (MappingRole.ORDER_ID, "order_id"),
            (MappingRole.AMOUNT, "total_amount"),
            (MappingRole.CHANNEL, "sales_channel"),
            (MappingRole.TIME, "ordered_at"),
        ),
    )
    metric = _metric(
        "alpha",
        1,
        "SUM(dataset_rows.total_amount)",
        "total_amount",
        dimensions=(MappingRole.CHANNEL,),
    )
    return resolve_dataset_scope(
        record,
        mapping,
        (metric,),
        _profile("staging_alpha_1", _DATASET_A_COLUMNS),
    )


def _scope_b() -> DatasetScope:
    record = _record("beta", 1, "staging_beta_1")
    mapping = _mapping(
        "beta",
        1,
        (
            (MappingRole.ORDER_ID, "txn_no"),
            (MappingRole.AMOUNT, "revenue"),
            (MappingRole.CHANNEL, "source"),
            (MappingRole.TIME, "transaction_date"),
        ),
    )
    metric = _metric(
        "beta",
        1,
        "SUM(dataset_rows.revenue)",
        "revenue",
        dimensions=(MappingRole.CHANNEL,),
    )
    return resolve_dataset_scope(
        record,
        mapping,
        (metric,),
        _profile("staging_beta_1", _DATASET_B_COLUMNS),
    )


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="按渠道统计销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        limit=10,
    )


def _request(*, dataset_id: str | None = None) -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-DS-001",
        user_id="USER-001",
        question="按渠道统计销售额",
        max_rows=10,
        dataset_id=dataset_id,
        dataset_version=1 if dataset_id is not None else None,
    )


# --- 跨数据集同一指标语义 ----------------------------------------------


def test_two_datasets_resolve_to_same_metric_semantics() -> None:
    scope_a = _scope_a()
    scope_b = _scope_b()

    metric_a = scope_a.metric_catalog.get(AnalysisMetric.SALES_AMOUNT)
    metric_b = scope_b.metric_catalog.get(AnalysisMetric.SALES_AMOUNT)

    assert metric_a.metric is metric_b.metric is AnalysisMetric.SALES_AMOUNT
    assert metric_a.source_columns == ("dataset_rows.total_amount",)
    assert metric_b.source_columns == ("dataset_rows.revenue",)
    assert (
        scope_a.dimension_columns[AnalysisDimension.CHANNEL]
        == "dataset_rows.sales_channel"
    )
    assert (
        scope_b.dimension_columns[AnalysisDimension.CHANNEL]
        == "dataset_rows.source"
    )
    assert scope_a.time_column == "dataset_rows.ordered_at"
    assert scope_b.time_column == "dataset_rows.transaction_date"
    assert "total_amount" in scope_a.allowed_columns["dataset_rows"]
    assert "revenue" not in scope_a.allowed_columns["dataset_rows"]
    assert "revenue" in scope_b.allowed_columns["dataset_rows"]
    assert scope_a.sql_table("dataset_rows") == "staging_alpha_1.dataset_rows"
    assert scope_b.sql_table("dataset_rows") == "staging_beta_1.dataset_rows"


def test_scope_rejects_unconfirmed_mapping() -> None:
    record = _record("alpha", 1, "staging_alpha_1")
    mapping = _mapping(
        "alpha",
        1,
        ((MappingRole.AMOUNT, "total_amount"),),
        confirmed=False,
    )
    metric = _metric("alpha", 1, "SUM(dataset_rows.total_amount)", "total_amount")

    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        resolve_dataset_scope(
            record,
            mapping,
            (metric,),
            _profile("staging_alpha_1", _DATASET_A_COLUMNS),
        )
    assert exc_info.value.reason_code == "dataset_mapping_unconfirmed"


def test_scope_rejects_no_confirmed_metrics() -> None:
    record = _record("alpha", 1, "staging_alpha_1")
    mapping = _mapping(
        "alpha",
        1,
        ((MappingRole.AMOUNT, "total_amount"),),
    )
    metric = _metric(
        "alpha",
        1,
        "SUM(dataset_rows.total_amount)",
        "total_amount",
        status=MetricStatus.PROPOSED,
    )

    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        resolve_dataset_scope(
            record,
            mapping,
            (metric,),
            _profile("staging_alpha_1", _DATASET_A_COLUMNS),
        )
    assert exc_info.value.reason_code == "dataset_no_metrics"


def test_scope_rejects_metrics_outside_supported_ids() -> None:
    record = _record("alpha", 1, "staging_alpha_1")
    mapping = _mapping(
        "alpha",
        1,
        ((MappingRole.AMOUNT, "total_amount"),),
    )
    metric = _metric(
        "alpha",
        1,
        "COUNT(DISTINCT dataset_rows.order_id)",
        "order_id",
        metric_id="refund_rate",
    )

    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        resolve_dataset_scope(
            record,
            mapping,
            (metric,),
            _profile("staging_alpha_1", _DATASET_A_COLUMNS),
        )
    assert exc_info.value.reason_code == "dataset_no_metrics"


# --- DatasetScopeResolver 拒绝路径 -------------------------------------


def _resolver(
    record: DatasetRecord | None,
    metrics: tuple[DatasetMetric, ...] = (),
) -> DatasetScopeResolver:
    registry = Mock()
    registry.get.return_value = record
    registry.list_metrics.return_value = metrics
    return DatasetScopeResolver(registry, Mock(), Mock())


def test_resolver_rejects_unknown_dataset() -> None:
    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        _resolver(None).resolve("missing")
    assert exc_info.value.reason_code == "dataset_not_found"


def test_resolver_rejects_archived_dataset() -> None:
    record = _record(
        "alpha",
        1,
        "staging_alpha_1",
        status=DatasetStatus.ARCHIVED,
    )
    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        _resolver(record).resolve("alpha", 1)
    assert exc_info.value.reason_code == "dataset_archived"


def test_resolver_rejects_not_ready_dataset() -> None:
    record = _record(
        "alpha",
        1,
        "staging_alpha_1",
        status=DatasetStatus.NEEDS_MAPPING,
    )
    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        _resolver(record).resolve("alpha", 1)
    assert exc_info.value.reason_code == "dataset_not_ready"


def test_resolver_rejects_unconfirmed_mapping() -> None:
    record = _record("alpha", 1, "staging_alpha_1", mapping_confirmed=False)
    with pytest.raises(DatasetScopeRejectionError) as exc_info:
        _resolver(record).resolve("alpha", 1)
    assert exc_info.value.reason_code == "dataset_mapping_unconfirmed"


# --- SQL 隔离：只能访问当前数据集 schema/列 ---------------------------


def test_sql_validation_accepts_own_dataset_sql() -> None:
    scope_a = _scope_a()
    sql = (
        "SELECT dataset_rows.sales_channel AS channel, "
        "SUM(dataset_rows.total_amount) AS sales_amount "
        "FROM staging_alpha_1.dataset_rows "
        "GROUP BY dataset_rows.sales_channel "
        "LIMIT 10"
    )

    prepared = prepare_safe_sql(
        sql,
        max_rows=10,
        access_role=AccessRole.ANALYST,
        allowed_columns=scope_a.allowed_columns,
        allowed_schema=scope_a.schema_name,
    )

    assert prepared.tables == ("dataset_rows",)


def test_sql_validation_blocks_other_dataset_schema() -> None:
    scope_a = _scope_a()
    sql = (
        "SELECT dataset_rows.source, "
        "SUM(dataset_rows.revenue) AS sales_amount "
        "FROM staging_beta_1.dataset_rows "
        "GROUP BY dataset_rows.source "
        "LIMIT 10"
    )

    with pytest.raises(SQLSafetyError, match="outside the allowed schema"):
        prepare_safe_sql(
            sql,
            max_rows=10,
            access_role=AccessRole.ANALYST,
            allowed_columns=scope_a.allowed_columns,
            allowed_schema=scope_a.schema_name,
        )


def test_glot_validation_tool_enforces_scope_schema() -> None:
    scope_a = _scope_a()
    tool = SQLGlotValidationTool(audit_sink=Mock())
    sql = (
        "SELECT dataset_rows.source, "
        "SUM(dataset_rows.revenue) AS sales_amount "
        "FROM staging_beta_1.dataset_rows "
        "GROUP BY dataset_rows.source "
        "LIMIT 10"
    )

    with pytest.raises(SQLValidationToolError, match="outside the allowed schema"):
        tool.validate(
            request_id="REQ-DS-001",
            user_id="USER-001",
            sql=sql,
            max_rows=10,
            access_role=AccessRole.ANALYST,
            scope=scope_a,
        )


def test_sql_validation_blocks_foreign_columns_in_own_schema() -> None:
    scope_a = _scope_a()
    sql = (
        "SELECT dataset_rows.source, "
        "SUM(dataset_rows.revenue) AS sales_amount "
        "FROM staging_alpha_1.dataset_rows "
        "GROUP BY dataset_rows.source "
        "LIMIT 10"
    )

    with pytest.raises(SQLSafetyError, match="column is not allowed"):
        prepare_safe_sql(
            sql,
            max_rows=10,
            access_role=AccessRole.ANALYST,
            allowed_columns=scope_a.allowed_columns,
            allowed_schema=scope_a.schema_name,
        )


# --- 目录检索与 SQL 生成契约只使用当前数据集 --------------------------


def test_catalog_retrieval_returns_only_own_dataset_evidence() -> None:
    scope_a = _scope_a()
    plan = _plan()

    evidence = CatalogRetrievalTool().retrieve(plan, scope=scope_a)

    source_ids = {item.source_id for item in evidence}
    assert "metric.sales_amount.v1" in source_ids
    assert "schema.dataset_rows" in source_ids
    assert not any("beta" in item.content for item in evidence)
    assert not any("revenue" in item.content for item in evidence)


def test_sql_generation_contract_uses_own_dataset_fields() -> None:
    scope_a = _scope_a()
    scope_b = _scope_b()
    plan = _plan()

    contract_a = _sql_generation_contract(
        plan,
        CatalogRetrievalTool().retrieve(plan, scope=scope_a),
        scope=scope_a,
    )
    contract_b = _sql_generation_contract(
        plan,
        CatalogRetrievalTool().retrieve(plan, scope=scope_b),
        scope=scope_b,
    )

    assert contract_a["required_tables"] == ["staging_alpha_1.dataset_rows"]
    assert contract_b["required_tables"] == ["staging_beta_1.dataset_rows"]
    assert (
        contract_a["required_group_by_clause"]
        == "GROUP BY dataset_rows.sales_channel"
    )
    assert (
        contract_b["required_group_by_clause"] == "GROUP BY dataset_rows.source"
    )
    assert (
        contract_a["metric_outputs"][0]["formula"]
        == "SUM(dataset_rows.total_amount)"
    )
    assert (
        contract_b["metric_outputs"][0]["formula"]
        == "SUM(dataset_rows.revenue)"
    )
    assert "revenue" not in str(contract_a)
    assert "total_amount" not in str(contract_b)


# --- workflow scope 节点：解析、拒绝与安全审计 -------------------------


def test_workflow_scope_node_rejects_dataset_with_security_audit() -> None:
    resolver = Mock()
    resolver.resolve.side_effect = DatasetScopeRejectionError(
        "dataset_archived",
        "该数据集已归档。",
    )
    audit_sink = Mock()
    node = create_domain_scope_node(
        Mock(),
        dataset_resolver=resolver,
        audit_sink=audit_sink,
    )
    state = create_initial_state(_request(dataset_id="alpha"))

    update = node(state)

    assert update["scope_supported"] is False
    assert update["scope_rejection_reason"] == "dataset_archived"
    audit_sink.record.assert_called_once()
    record = audit_sink.record.call_args.args[0]
    assert record.status is QueryAuditStatus.REJECTED
    assert record.original_sql == ""
    assert record.reason == "dataset_dataset_archived"


def test_workflow_scope_node_accepts_dataset_scope() -> None:
    scope = _scope_a()
    resolver = Mock()
    resolver.resolve.return_value = scope
    node = create_domain_scope_node(Mock(), dataset_resolver=resolver)
    state = create_initial_state(_request(dataset_id="alpha"))

    update = node(state)

    assert update["scope_supported"] is True
    assert update["dataset_scope"] == scope
    assert update["dataset_name"] == "数据集 alpha"
    assert update["dataset_schema"] == "staging_alpha_1"
    resolver.resolve.assert_called_once_with("alpha", 1)


def test_workflow_scope_node_rejects_unavailable_dataset_support() -> None:
    node = create_domain_scope_node(Mock())
    state = create_initial_state(_request(dataset_id="alpha"))

    update = node(state)

    assert update["scope_supported"] is False
    assert update["scope_rejection_reason"] == "dataset_unavailable"


def test_workflow_end_to_end_uses_dataset_scope() -> None:
    scope = _scope_a()
    plan = _plan()
    sql = (
        "SELECT dataset_rows.sales_channel AS channel, "
        "SUM(dataset_rows.total_amount) AS sales_amount "
        "FROM staging_alpha_1.dataset_rows "
        "GROUP BY dataset_rows.sales_channel "
        "LIMIT 10"
    )
    planner = Mock()
    planner.plan.return_value = plan
    generator = Mock()
    generator.generate.return_value = sql
    safety_tool = Mock()
    safety_tool.validate.return_value = prepare_safe_sql(
        sql,
        max_rows=10,
        access_role=AccessRole.ANALYST,
        allowed_columns=scope.allowed_columns,
        allowed_schema=scope.schema_name,
    )
    execution_tool = Mock()
    execution_tool.execute.return_value = Mock(
        rows=[{"channel": "淘宝", "sales_amount": "5200.00"}]
    )
    summarizer = Mock()
    summarizer.summarize.return_value = (
        "统计来自数据集 alpha：淘宝渠道销售额为 5200.00 元。"
    )
    resolver = Mock()
    resolver.resolve.return_value = scope
    nodes = create_workflow_nodes(
        planner=planner,
        retrieval_tool=CatalogRetrievalTool(),
        sql_generator=generator,
        validation_tool=safety_tool,
        business_validation_tool=SQLConsistencyValidationTool(),
        approval_audit_sink=Mock(),
        execution_tool=execution_tool,
        summarizer=summarizer,
        domain_gate=Mock(),
        dataset_resolver=resolver,
    )

    result = build_analysis_graph(nodes).invoke(
        create_initial_state(_request(dataset_id="alpha"))
    )

    assert result["scope_supported"] is True
    assert result["dataset_scope"] == scope
    assert result["sql_valid"] is True
    assert result["business_sql_valid"] is True
    assert result["final_answer"] == (
        "统计来自数据集 alpha：淘宝渠道销售额为 5200.00 元。"
    )
    resolver.resolve.assert_called_once_with("alpha", 1)
    assert generator.generate.call_args.kwargs["scope"] is scope
    assert safety_tool.validate.call_args.kwargs["scope"] is scope
    assert summarizer.summarize.call_args.kwargs["dataset_name"] == "数据集 alpha"


# --- 公开拒答消息与 public demo 限制 -----------------------------------


def test_public_rejection_messages_cover_dataset_codes() -> None:
    for code in (
        "dataset_not_found",
        "dataset_archived",
        "dataset_not_ready",
        "dataset_mapping_unconfirmed",
        "dataset_no_metrics",
        "dataset_unavailable",
    ):
        assert code in _PUBLIC_REJECTION_MESSAGES


def test_public_demo_rejects_dataset_requests() -> None:
    from retail_analytics_agent.app import _enforce_public_demo_request

    settings = SimpleNamespace(
        public_demo_mode=True,
        public_demo_max_rows=10,
        public_demo_rate_limit_per_minute=1000,
    )
    http_request = Mock(client=Mock(host="127.0.0.1"))

    with pytest.raises(Exception) as exc_info:
        _enforce_public_demo_request(
            http_request,
            _request(dataset_id="alpha"),
            settings,
        )
    assert exc_info.value.status_code == 403


def test_public_demo_allows_requests_without_dataset() -> None:
    from retail_analytics_agent.app import _enforce_public_demo_request

    settings = SimpleNamespace(
        public_demo_mode=True,
        public_demo_max_rows=10,
        public_demo_rate_limit_per_minute=1000,
    )
    http_request = Mock(client=Mock(host="127.0.0.1"))

    _enforce_public_demo_request(http_request, _request(), settings)
