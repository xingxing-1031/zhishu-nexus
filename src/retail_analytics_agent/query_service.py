from dataclasses import dataclass
from time import perf_counter

from retail_analytics_agent.audit import (
    AuditSink,
    QueryAuditRecord,
    QueryAuditStatus,
)
from retail_analytics_agent.models import AccessRole
from retail_analytics_agent.database import DatabaseConnection, DatabaseRow
from retail_analytics_agent.sql_safety import (
    PreparedSQL,
    SQLSafetyError,
    prepare_safe_sql,
)


SET_TRANSACTION_READ_ONLY_SQL = "SET TRANSACTION READ ONLY"
SET_STATEMENT_TIMEOUT_SQL = """
SELECT set_config(
    'statement_timeout',
    %(statement_timeout)s,
    true
);
"""

MIN_STATEMENT_TIMEOUT_MS = 100
MAX_STATEMENT_TIMEOUT_MS = 30_000


@dataclass(frozen=True, slots=True)
class SafeQueryResult:
    rows: list[DatabaseRow]
    audit: QueryAuditRecord


def prepare_audited_sql(
    audit_sink: AuditSink,
    *,
    request_id: str,
    user_id: str,
    sql: str,
    max_rows: int = 100,
    access_role: AccessRole = AccessRole.ANALYST,
) -> PreparedSQL:
    """Prepare one generated query and audit policy rejections."""
    started_at = perf_counter()

    try:
        return prepare_safe_sql(
            sql,
            max_rows=max_rows,
            access_role=access_role,
        )
    except (SQLSafetyError, ValueError) as exc:
        audit = _build_audit(
            request_id=request_id,
            user_id=user_id,
            original_sql=sql,
            prepared=None,
            status=QueryAuditStatus.REJECTED,
            reason=str(exc),
            row_count=None,
            started_at=started_at,
        )
        audit_sink.record(audit)
        raise


def execute_prepared_query(
    connection: DatabaseConnection,
    audit_sink: AuditSink,
    *,
    request_id: str,
    user_id: str,
    original_sql: str,
    prepared_sql: PreparedSQL,
    statement_timeout_ms: int = 2_000,
) -> SafeQueryResult:
    """Execute an already validated query and preserve its original SQL."""
    started_at = perf_counter()

    try:
        _validate_timeout(statement_timeout_ms)
    except ValueError as exc:
        audit = _build_audit(
            request_id=request_id,
            user_id=user_id,
            original_sql=original_sql,
            prepared=prepared_sql,
            status=QueryAuditStatus.REJECTED,
            reason=str(exc),
            row_count=None,
            started_at=started_at,
        )
        audit_sink.record(audit)
        raise

    return _execute_prepared_query(
        connection,
        audit_sink,
        request_id=request_id,
        user_id=user_id,
        original_sql=original_sql,
        prepared=prepared_sql,
        statement_timeout_ms=statement_timeout_ms,
        started_at=started_at,
    )


def execute_safe_query(
    connection: DatabaseConnection,
    audit_sink: AuditSink,
    *,
    request_id: str,
    user_id: str,
    sql: str,
    max_rows: int = 100,
    statement_timeout_ms: int = 2_000,
    access_role: AccessRole = AccessRole.ANALYST,
) -> SafeQueryResult:
    """Validate, constrain, execute, and audit one generated query."""
    started_at = perf_counter()
    prepared: PreparedSQL | None = None

    try:
        _validate_timeout(statement_timeout_ms)
        prepared = prepare_safe_sql(
            sql,
            max_rows=max_rows,
            access_role=access_role,
        )
    except (SQLSafetyError, ValueError) as exc:
        audit = _build_audit(
            request_id=request_id,
            user_id=user_id,
            original_sql=sql,
            prepared=prepared,
            status=QueryAuditStatus.REJECTED,
            reason=str(exc),
            row_count=None,
            started_at=started_at,
        )
        audit_sink.record(audit)
        raise

    return _execute_prepared_query(
        connection,
        audit_sink,
        request_id=request_id,
        user_id=user_id,
        original_sql=sql,
        prepared=prepared,
        statement_timeout_ms=statement_timeout_ms,
        started_at=started_at,
    )


def _execute_prepared_query(
    connection: DatabaseConnection,
    audit_sink: AuditSink,
    *,
    request_id: str,
    user_id: str,
    original_sql: str,
    prepared: PreparedSQL,
    statement_timeout_ms: int,
    started_at: float,
) -> SafeQueryResult:
    try:
        connection.execute(SET_TRANSACTION_READ_ONLY_SQL)
        connection.execute(
            SET_STATEMENT_TIMEOUT_SQL,
            {"statement_timeout": f"{statement_timeout_ms}ms"},
        )
        rows = connection.execute(prepared.sql).fetchall()
        connection.commit()
    except Exception as exc:
        connection.rollback()
        audit = _build_audit(
            request_id=request_id,
            user_id=user_id,
            original_sql=original_sql,
            prepared=prepared,
            status=QueryAuditStatus.FAILED,
            reason=f"{type(exc).__name__}: {exc}",
            row_count=None,
            started_at=started_at,
        )
        audit_sink.record(audit)
        raise

    audit = _build_audit(
        request_id=request_id,
        user_id=user_id,
        original_sql=original_sql,
        prepared=prepared,
        status=QueryAuditStatus.SUCCEEDED,
        reason=None,
        row_count=len(rows),
        started_at=started_at,
    )
    audit_sink.record(audit)
    return SafeQueryResult(rows=rows, audit=audit)


def _validate_timeout(statement_timeout_ms: int) -> None:
    if not MIN_STATEMENT_TIMEOUT_MS <= statement_timeout_ms <= (
        MAX_STATEMENT_TIMEOUT_MS
    ):
        raise ValueError(
            "statement_timeout_ms must be between "
            f"{MIN_STATEMENT_TIMEOUT_MS} and {MAX_STATEMENT_TIMEOUT_MS}"
        )


def _build_audit(
    *,
    request_id: str,
    user_id: str,
    original_sql: str,
    prepared: PreparedSQL | None,
    status: QueryAuditStatus,
    reason: str | None,
    row_count: int | None,
    started_at: float,
) -> QueryAuditRecord:
    return QueryAuditRecord(
        request_id=request_id,
        user_id=user_id,
        original_sql=original_sql,
        executed_sql=prepared.sql if prepared is not None else None,
        status=status,
        reason=reason,
        row_count=row_count,
        duration_ms=(perf_counter() - started_at) * 1000,
    )
