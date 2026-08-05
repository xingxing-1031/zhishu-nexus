from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.models import (
    AccessRole,
    ApprovalResolutionRequest,
    ApprovalStatus,
    QueryRisk,
)
from retail_analytics_agent.sql_safety import PreparedSQL


SENSITIVE_APPROVAL_COLUMNS = frozenset({"refunds.reason"})
HIGH_RESULT_LIMIT = 100


def assess_query_risk(prepared_sql: PreparedSQL) -> QueryRisk:
    sensitive_columns = tuple(
        sorted(
            set(prepared_sql.referenced_columns)
            & SENSITIVE_APPROVAL_COLUMNS
        )
    )
    reasons: list[str] = []
    if sensitive_columns:
        reasons.append(
            "query reads sensitive columns: "
            + ", ".join(sensitive_columns)
        )
    if prepared_sql.result_limit > HIGH_RESULT_LIMIT:
        reasons.append(
            "query result limit exceeds "
            f"{HIGH_RESULT_LIMIT}: {prepared_sql.result_limit}"
        )
    return QueryRisk(
        requires_approval=bool(reasons),
        reasons=tuple(reasons),
        sensitive_columns=sensitive_columns,
        result_limit=prepared_sql.result_limit,
    )


class ApprovalAuditStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalAuditRecord(BaseModel):
    request_id: str = Field(min_length=1)
    requester_id: str = Field(min_length=1)
    access_role: AccessRole
    sql: str = Field(min_length=1)
    status: ApprovalAuditStatus
    reasons: tuple[str, ...] = Field(min_length=1)
    reviewer_id: str | None = None
    decision_reason: str | None = None

    @model_validator(mode="after")
    def validate_resolution_fields(self) -> "ApprovalAuditRecord":
        if self.status is ApprovalAuditStatus.PENDING:
            if self.reviewer_id is not None:
                raise ValueError("pending approval must not have a reviewer")
        elif self.reviewer_id is None:
            raise ValueError("resolved approval requires a reviewer")
        if (
            self.status is ApprovalAuditStatus.REJECTED
            and (
                self.decision_reason is None
                or not self.decision_reason.strip()
            )
        ):
            raise ValueError("rejected approval requires a reason")
        return self


class TrustedApprovalResolution(ApprovalResolutionRequest):
    reviewer_id: str = Field(min_length=1)
    reviewer_role: AccessRole


class ApprovalAuditSink(Protocol):
    def record(self, audit: ApprovalAuditRecord) -> None: ...


APPROVAL_AUDIT_INSERT_SQL = """
INSERT INTO query_approval_logs (
    event_key,
    request_id,
    requester_id,
    access_role,
    sql,
    status,
    reasons,
    reviewer_id,
    decision_reason
)
VALUES (
    %(event_key)s,
    %(request_id)s,
    %(requester_id)s,
    %(access_role)s,
    %(sql)s,
    %(status)s,
    %(reasons)s,
    %(reviewer_id)s,
    %(decision_reason)s
)
ON CONFLICT (event_key) DO NOTHING;
"""


def approval_audit_event_key(audit: ApprovalAuditRecord) -> str:
    phase = (
        "pending"
        if audit.status is ApprovalAuditStatus.PENDING
        else "resolution"
    )
    return f"approval:{audit.request_id}:{phase}"


class DatabaseApprovalAuditSink:
    def record(self, audit: ApprovalAuditRecord) -> None:
        with connect_to_database() as connection:
            payload = audit.model_dump(mode="json")
            payload["reasons"] = list(audit.reasons)
            payload["event_key"] = approval_audit_event_key(audit)
            connection.execute(APPROVAL_AUDIT_INSERT_SQL, payload)


def approval_status_for_risk(risk: QueryRisk) -> ApprovalStatus:
    if risk.requires_approval:
        return ApprovalStatus.PENDING
    return ApprovalStatus.NOT_REQUIRED
