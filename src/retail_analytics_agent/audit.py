import json
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, Field

from retail_analytics_agent.database import connect_to_database


class QueryAuditStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class QueryAuditRecord(BaseModel):
    request_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    original_sql: str
    executed_sql: str | None = None
    status: QueryAuditStatus
    reason: str | None = None
    row_count: int | None = Field(default=None, ge=0)
    duration_ms: float = Field(ge=0)


class AuditSink(Protocol):
    def record(self, audit: QueryAuditRecord) -> None: ...


AUDIT_INSERT_SQL = """
INSERT INTO query_audit_logs (
    event_key,
    request_id,
    user_id,
    original_sql,
    executed_sql,
    status,
    reason,
    row_count,
    duration_ms
)
VALUES (
    %(event_key)s,
    %(request_id)s,
    %(user_id)s,
    %(original_sql)s,
    %(executed_sql)s,
    %(status)s,
    %(reason)s,
    %(row_count)s,
    %(duration_ms)s
)
ON CONFLICT (event_key) DO NOTHING;
"""


def query_audit_event_key(audit: QueryAuditRecord) -> str:
    payload = audit.model_dump(mode="json", exclude={"duration_ms"})
    digest = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"query:{audit.request_id}:{digest}"


class DatabaseAuditSink:
    """Persist audit events in a transaction separate from the query."""

    def record(self, audit: QueryAuditRecord) -> None:
        with connect_to_database() as connection:
            payload = audit.model_dump(mode="json")
            payload["event_key"] = query_audit_event_key(audit)
            connection.execute(
                AUDIT_INSERT_SQL,
                payload,
            )
