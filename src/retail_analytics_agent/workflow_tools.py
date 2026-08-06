from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from retail_analytics_agent.audit import AuditSink
from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    DEFAULT_SCHEMA_CATALOG,
    MetricCatalog,
    MetricDefinition,
    SchemaCatalog,
)
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisDimension,
    AnalysisFilterField,
    AnalysisPlan,
    RetrievalEvidence,
)
from retail_analytics_agent.query_service import (
    SafeQueryResult,
    execute_prepared_query,
    prepare_audited_sql,
)
from retail_analytics_agent.resilience import (
    WorkflowDeadlineExceeded,
    remaining_workflow_seconds,
)
from retail_analytics_agent.sql_safety import PreparedSQL, SQLSafetyError
from retail_analytics_agent.sql_consistency import (
    SQLBusinessConsistencyError,
    SQLConsistencyResult,
    validate_sql_against_evidence,
)


class SQLValidationToolError(ValueError):
    """Stable workflow-facing error for rejected generated SQL."""


class SQLExecutionToolError(RuntimeError):
    """Stable workflow-facing error for database execution failures."""


class SQLBusinessConsistencyToolError(ValueError):
    """Stable workflow-facing error for business-invalid SQL."""


class CatalogRetrievalToolError(ValueError):
    """Stable workflow-facing error for unsupported catalog retrieval."""


class RetrievalTool(Protocol):
    def retrieve(self, plan: AnalysisPlan) -> list[RetrievalEvidence]: ...


class SQLValidationTool(Protocol):
    def validate(
        self,
        *,
        request_id: str,
        user_id: str,
        sql: str,
        max_rows: int,
        access_role: AccessRole,
    ) -> PreparedSQL: ...


class SQLBusinessConsistencyTool(Protocol):
    def validate(
        self,
        *,
        sql: str,
        plan: AnalysisPlan,
        evidence: Sequence[RetrievalEvidence],
    ) -> SQLConsistencyResult: ...


class SQLExecutionTool(Protocol):
    def execute(
        self,
        *,
        request_id: str,
        user_id: str,
        original_sql: str,
        prepared_sql: PreparedSQL,
    ) -> SafeQueryResult: ...


_DIMENSION_TABLES = {
    AnalysisDimension.CHANNEL: "orders",
    AnalysisDimension.PRODUCT: "products",
    AnalysisDimension.CATEGORY: "products",
    AnalysisDimension.ORDER_STATUS: "orders",
    AnalysisDimension.REFUND_STATUS: "refunds",
}

_FILTER_TABLES = {
    AnalysisFilterField.CHANNEL: "orders",
    AnalysisFilterField.ORDER_STATUS: "orders",
    AnalysisFilterField.PRODUCT_ID: "products",
    AnalysisFilterField.CATEGORY: "products",
    AnalysisFilterField.REFUND_STATUS: "refunds",
}


@dataclass(frozen=True, slots=True)
class CatalogRetrievalTool:
    """Retrieve the minimum catalog evidence required by an analysis plan."""

    metric_catalog: MetricCatalog = DEFAULT_METRIC_CATALOG
    schema_catalog: SchemaCatalog = DEFAULT_SCHEMA_CATALOG

    def retrieve(self, plan: AnalysisPlan) -> list[RetrievalEvidence]:
        metric_definitions = [
            self.metric_catalog.get(metric) for metric in plan.metrics
        ]
        self._validate_dimensions(plan, metric_definitions)

        required_tables = {
            table_name
            for definition in metric_definitions
            for table_name in definition.source_tables
        }
        required_tables.update(
            _DIMENSION_TABLES[dimension]
            for dimension in plan.dimensions
            if dimension in _DIMENSION_TABLES
        )
        required_tables.update(
            _FILTER_TABLES[item.field]
            for item in plan.filters
            if item.field in _FILTER_TABLES
        )

        join_indexes = self._find_required_join_indexes(required_tables)
        selected_tables = set(required_tables)
        for index in join_indexes:
            join = self.schema_catalog.joins[index]
            selected_tables.update((join.left_table, join.right_table))

        evidence = [
            definition.to_evidence() for definition in metric_definitions
        ]
        evidence.extend(
            table.to_evidence()
            for table in self.schema_catalog.tables
            if table.table_name in selected_tables
        )
        evidence.extend(
            join.to_evidence()
            for index, join in enumerate(self.schema_catalog.joins)
            if index in join_indexes
        )
        return evidence

    def _validate_dimensions(
        self,
        plan: AnalysisPlan,
        metric_definitions: list[MetricDefinition],
    ) -> None:
        for definition in metric_definitions:
            unsupported = set(plan.dimensions) - set(
                definition.supported_dimensions
            )
            if unsupported:
                names = ", ".join(sorted(item.value for item in unsupported))
                raise CatalogRetrievalToolError(
                    f"metric {definition.metric.value} does not support "
                    f"dimensions: {names}"
                )

    def _find_required_join_indexes(self, required_tables: set[str]) -> set[int]:
        if not required_tables:
            return set()

        known_tables = {
            table.table_name for table in self.schema_catalog.tables
        }
        unknown_tables = required_tables - known_tables
        if unknown_tables:
            raise CatalogRetrievalToolError(
                "schema tables not found: " + ", ".join(sorted(unknown_tables))
            )

        table_order = [
            table.table_name
            for table in self.schema_catalog.tables
            if table.table_name in required_tables
        ]
        connected = {table_order[0]}
        selected_joins: set[int] = set()

        for target in table_order[1:]:
            if target in connected:
                continue
            path = self._shortest_join_path(connected, target)
            if path is None:
                raise CatalogRetrievalToolError(
                    f"no approved join path to schema table: {target}"
                )
            for index in path:
                join = self.schema_catalog.joins[index]
                selected_joins.add(index)
                connected.update((join.left_table, join.right_table))

        return selected_joins

    def _shortest_join_path(
        self,
        connected: set[str],
        target: str,
    ) -> list[int] | None:
        queue = deque((table_name, []) for table_name in connected)
        visited = set(connected)
        while queue:
            table_name, path = queue.popleft()
            if table_name == target:
                return path
            for index, join in enumerate(self.schema_catalog.joins):
                if join.left_table == table_name:
                    neighbor = join.right_table
                elif join.right_table == table_name:
                    neighbor = join.left_table
                else:
                    continue
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path, index]))
        return None


@dataclass(slots=True)
class SQLGlotValidationTool:
    audit_sink: AuditSink

    def validate(
        self,
        *,
        request_id: str,
        user_id: str,
        sql: str,
        max_rows: int,
        access_role: AccessRole,
    ) -> PreparedSQL:
        try:
            return prepare_audited_sql(
                self.audit_sink,
                request_id=request_id,
                user_id=user_id,
                sql=sql,
                max_rows=max_rows,
                access_role=access_role,
            )
        except (SQLSafetyError, ValueError) as exc:
            raise SQLValidationToolError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SQLConsistencyValidationTool:
    """Adapter from the workflow tool contract to the pure SQL validator."""

    metric_catalog: MetricCatalog = DEFAULT_METRIC_CATALOG
    schema_catalog: SchemaCatalog = DEFAULT_SCHEMA_CATALOG

    def validate(
        self,
        *,
        sql: str,
        plan: AnalysisPlan,
        evidence: Sequence[RetrievalEvidence],
    ) -> SQLConsistencyResult:
        try:
            return validate_sql_against_evidence(
                sql,
                plan=plan,
                evidence=evidence,
                metric_catalog=self.metric_catalog,
                schema_catalog=self.schema_catalog,
            )
        except SQLBusinessConsistencyError as exc:
            raise SQLBusinessConsistencyToolError(str(exc)) from exc


@dataclass(slots=True)
class SafeSQLExecutionTool:
    connection: DatabaseConnection
    audit_sink: AuditSink
    statement_timeout_ms: int = 2_000

    def execute(
        self,
        *,
        request_id: str,
        user_id: str,
        original_sql: str,
        prepared_sql: PreparedSQL,
    ) -> SafeQueryResult:
        try:
            statement_timeout_ms = self.statement_timeout_ms
            remaining = remaining_workflow_seconds()
            if remaining is not None:
                if remaining < 0.1:
                    raise WorkflowDeadlineExceeded(
                        "workflow time budget exhausted before SQL execution"
                    )
                statement_timeout_ms = min(
                    statement_timeout_ms,
                    int(remaining * 1000),
                )
            return execute_prepared_query(
                self.connection,
                self.audit_sink,
                request_id=request_id,
                user_id=user_id,
                original_sql=original_sql,
                prepared_sql=prepared_sql,
                statement_timeout_ms=statement_timeout_ms,
            )
        except Exception as exc:
            raise SQLExecutionToolError(
                f"{type(exc).__name__}: {exc}"
            ) from exc
