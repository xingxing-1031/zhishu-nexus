from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.agent_models import AgentMode
from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.dataset_models import DatasetStatus
from retail_analytics_agent.knowledge import DEFAULT_METRIC_CATALOG
from retail_analytics_agent.metric_models import MetricStatus
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
    conversation_id: str | None = None
    user_id: str
    access_role: AccessRole
    agent_mode: AgentMode
    original_question: str
    status: AdminAuditStatus
    row_count: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    max_rows: int | None = Field(default=None, ge=1, le=1000)
    approval_required: bool
    tool_names: tuple[str, ...] = ()
    evidence_count: int = Field(default=0, ge=0)
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


class DatasetMetricView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    name: str
    version: str
    definition: str
    formula: str
    source_table: str
    source_column: str
    supported_dimensions: tuple[str, ...]


class DatasetAnalystView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    dataset_name: str
    version: int
    source_type: str
    row_count: int
    schema_name: str
    status: str
    metrics: tuple[DatasetMetricView, ...] = ()


ADMIN_AUDIT_SELECT_SQL = """
SELECT run.request_id,
       run.conversation_id,
       run.user_id,
       run.access_role,
       run.agent_mode,
       run.original_question,
       CASE run.status
           WHEN 'pending' THEN 'approval_required'
           WHEN 'refused' THEN 'rejected'
           ELSE run.status
       END AS status,
       query_event.row_count,
       COALESCE(run.duration_ms, query_event.duration_ms) AS duration_ms,
       registry.max_rows,
       (run.approval_required OR approval_event.request_id IS NOT NULL)
           AS approval_required,
       run.tool_names,
       run.evidence_count,
       run.created_at,
       run.updated_at
FROM agent_request_runs AS run
LEFT JOIN analysis_request_registry AS registry
    ON registry.request_id = run.request_id
LEFT JOIN LATERAL (
    SELECT row_count, duration_ms
    FROM query_audit_logs
    WHERE request_id = run.request_id
    ORDER BY audit_id DESC
    LIMIT 1
) AS query_event ON TRUE
LEFT JOIN LATERAL (
    SELECT request_id
    FROM query_approval_logs
    WHERE request_id = run.request_id
    ORDER BY approval_audit_id DESC
    LIMIT 1
) AS approval_event ON TRUE
WHERE run.auditable = TRUE
  AND (CAST(%(request_id)s AS text) IS NULL OR run.request_id = %(request_id)s)
  AND (CAST(%(user_id)s AS text) IS NULL OR run.user_id = %(user_id)s)
  AND (
      CAST(%(agent_mode)s AS text) IS NULL
      OR run.agent_mode = %(agent_mode)s
  )
  AND (
      CAST(%(status)s AS text) IS NULL
      OR CASE run.status
          WHEN 'pending' THEN 'approval_required'
          WHEN 'refused' THEN 'rejected'
          ELSE run.status
      END = %(status)s
  )
  AND (
      CAST(%(approval_required)s AS boolean) IS NULL
      OR (run.approval_required OR approval_event.request_id IS NOT NULL)
          = %(approval_required)s
  )
  AND run.created_at >= CURRENT_TIMESTAMP - make_interval(days => %(days)s)
ORDER BY run.created_at DESC
LIMIT %(limit)s;
"""


def list_admin_audit_entries(
    connection: DatabaseConnection,
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    agent_mode: AgentMode | None = None,
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
            "agent_mode": agent_mode.value if agent_mode is not None else None,
            "status": status.value if status is not None else None,
            "approval_required": approval_required,
            "days": days,
            "limit": limit,
        },
    ).fetchall()
    return tuple(AdminAuditEntry.model_validate(row) for row in rows)


def list_analyst_datasets(registry) -> tuple[DatasetAnalystView, ...]:
    """Only ready datasets with their confirmed metric catalog are visible.

    Analysts may pick a ready dataset and must see the version, row count and
    confirmed metric definitions (口径/数据来源) that the analysis will use.
    """
    views: list[DatasetAnalystView] = []
    for record in registry.list_active():
        if record.status is not DatasetStatus.READY:
            continue
        metrics = tuple(
            DatasetMetricView(
                metric_id=metric.metric_id,
                name=metric.name,
                version=metric.metric_version,
                definition=metric.definition,
                formula=metric.formula,
                source_table=metric.source_table,
                source_column=metric.source_column,
                supported_dimensions=tuple(
                    item.value for item in metric.supported_dimensions
                ),
            )
            for metric in registry.list_metrics(record.dataset_id, record.version)
            if metric.status is MetricStatus.CONFIRMED
        )
        views.append(
            DatasetAnalystView(
                dataset_id=record.dataset_id,
                dataset_name=record.dataset_name,
                version=record.version,
                source_type=record.source_type.value,
                row_count=record.row_count,
                schema_name=record.schema_name,
                status=record.status.value,
                metrics=metrics,
            )
        )
    return tuple(views)


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
