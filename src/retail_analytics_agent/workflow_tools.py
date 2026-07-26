from dataclasses import dataclass
from typing import Protocol

from retail_analytics_agent.audit import AuditSink
from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.models import AnalysisPlan, RetrievalEvidence
from retail_analytics_agent.query_service import (
    SafeQueryResult,
    execute_prepared_query,
    prepare_audited_sql,
)
from retail_analytics_agent.sql_safety import PreparedSQL, SQLSafetyError


class SQLValidationToolError(ValueError):
    """Stable workflow-facing error for rejected generated SQL."""


class SQLExecutionToolError(RuntimeError):
    """Stable workflow-facing error for database execution failures."""


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
    ) -> PreparedSQL: ...


class SQLExecutionTool(Protocol):
    def execute(
        self,
        *,
        request_id: str,
        user_id: str,
        original_sql: str,
        prepared_sql: PreparedSQL,
    ) -> SafeQueryResult: ...


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
    ) -> PreparedSQL:
        try:
            return prepare_audited_sql(
                self.audit_sink,
                request_id=request_id,
                user_id=user_id,
                sql=sql,
                max_rows=max_rows,
            )
        except (SQLSafetyError, ValueError) as exc:
            raise SQLValidationToolError(str(exc)) from exc


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
            return execute_prepared_query(
                self.connection,
                self.audit_sink,
                request_id=request_id,
                user_id=user_id,
                original_sql=original_sql,
                prepared_sql=prepared_sql,
                statement_timeout_ms=self.statement_timeout_ms,
            )
        except Exception as exc:
            raise SQLExecutionToolError(
                f"{type(exc).__name__}: {exc}"
            ) from exc
