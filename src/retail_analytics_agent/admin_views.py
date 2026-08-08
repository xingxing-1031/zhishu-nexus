from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.knowledge import DEFAULT_METRIC_CATALOG
from retail_analytics_agent.models import AccessRole


class AdminAuditStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    APPROVAL_REQUIRED = "approval_required"
    REJECTED = "rejected"
    DEGRADED = "degraded"
    FAILED = "failed"


class AdminAuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    user_id: str
    access_role: AccessRole
    original_question: str
    status: AdminAuditStatus
    row_count: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    max_rows: int | None = Field(default=None, ge=1, le=1000)
    approval_required: bool
    created_at: datetime
    updated_at: datetime


class MetricDefinitionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    name: str
    version: str
    description: str
    formula: str
    source_tables: tuple[str, ...]
    fixed_rules: tuple[str, ...]
    supported_dimensions: tuple[str, ...]


ADMIN_AUDIT_SELECT_SQL = """
SELECT registry.request_id,
       registry.user_id,
       registry.access_role,
       COALESCE(
           registry.original_question,
           '历史请求（未记录原始问题）'
       ) AS original_question,
       CASE registry.status
           WHEN 'completed' THEN 'succeeded'
           WHEN 'pending' THEN 'approval_required'
           ELSE registry.status
       END AS status,
       query_event.row_count,
       query_event.duration_ms,
       registry.max_rows,
       (approval_event.request_id IS NOT NULL) AS approval_required,
       registry.created_at,
       registry.updated_at
FROM analysis_request_registry AS registry
LEFT JOIN LATERAL (
    SELECT row_count, duration_ms
    FROM query_audit_logs
    WHERE request_id = registry.request_id
    ORDER BY audit_id DESC
    LIMIT 1
) AS query_event ON TRUE
LEFT JOIN LATERAL (
    SELECT request_id
    FROM query_approval_logs
    WHERE request_id = registry.request_id
    ORDER BY approval_audit_id DESC
    LIMIT 1
) AS approval_event ON TRUE
WHERE (CAST(%(request_id)s AS text) IS NULL OR registry.request_id = %(request_id)s)
  AND (CAST(%(user_id)s AS text) IS NULL OR registry.user_id = %(user_id)s)
  AND (
      CAST(%(status)s AS text) IS NULL
      OR CASE registry.status
          WHEN 'completed' THEN 'succeeded'
          WHEN 'pending' THEN 'approval_required'
          ELSE registry.status
      END = %(status)s
  )
  AND (
      CAST(%(approval_required)s AS boolean) IS NULL
      OR (approval_event.request_id IS NOT NULL) = %(approval_required)s
  )
  AND registry.created_at >= CURRENT_TIMESTAMP - make_interval(days => %(days)s)
ORDER BY registry.created_at DESC
LIMIT %(limit)s;
"""


def list_admin_audit_entries(
    connection: DatabaseConnection,
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    status: AdminAuditStatus | None = None,
    approval_required: bool | None = None,
    days: int = 30,
    limit: int = 100,
) -> tuple[AdminAuditEntry, ...]:
    rows = connection.execute(
        ADMIN_AUDIT_SELECT_SQL,
        {
            "request_id": request_id,
            "user_id": user_id,
            "status": status.value if status is not None else None,
            "approval_required": approval_required,
            "days": days,
            "limit": limit,
        },
    ).fetchall()
    return tuple(AdminAuditEntry.model_validate(row) for row in rows)


def list_metric_definitions() -> tuple[MetricDefinitionView, ...]:
    return tuple(
        MetricDefinitionView(
            source_id=definition.source_id,
            name=definition.display_name,
            version=definition.version,
            description=definition.description,
            formula=definition.formula,
            source_tables=definition.source_tables,
            fixed_rules=tuple(
                f"{item.field.value} {item.operator.value} {item.value}"
                for item in definition.fixed_filters
            ),
            supported_dimensions=tuple(
                item.value for item in definition.supported_dimensions
            ),
        )
        for definition in DEFAULT_METRIC_CATALOG.definitions
    )
