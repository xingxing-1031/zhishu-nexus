from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from threading import RLock
from typing import Protocol

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentTaskStatus,
)
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.models import AccessContext, AccessRole


class AgentRunClaimStatus(StrEnum):
    NEW = "new"
    EXISTING = "existing"
    CONFLICT = "conflict"


class AgentRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    request_fingerprint: str = Field(min_length=64, max_length=64)
    conversation_id: str | None = None
    user_id: str
    access_role: AccessRole
    agent_mode: AgentMode
    original_question: str
    auditable: bool
    status: AgentTaskStatus
    tool_names: tuple[str, ...] = ()
    evidence_count: int = Field(default=0, ge=0)
    approval_required: bool = False
    failure_reason: str | None = None
    response: AgentResponse | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AgentRunClaim:
    status: AgentRunClaimStatus
    record: AgentRunRecord


class AgentRunStore(Protocol):
    def claim(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        mode: AgentMode,
        auditable: bool,
    ) -> AgentRunClaim: ...

    def complete(self, response: AgentResponse, *, duration_ms: float) -> None: ...

    def fail(self, request_id: str, reason: str, *, duration_ms: float) -> None: ...

    def get(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> AgentRunRecord | None: ...


_ENTERPRISE_AUDIT_TERMS = {
    "公司",
    "企业",
    "内部",
    "数据库",
    "知识库",
    "制度",
    "规定",
    "权限",
    "敏感",
    "订单",
    "销售",
    "经营",
    "退款",
    "商品",
    "客户",
    "员工",
    "sql",
    "database",
}


def is_auditable_agent_request(question: str, mode: AgentMode) -> bool:
    if mode is not AgentMode.GENERAL:
        return True
    normalized = question.casefold()
    return any(term.casefold() in normalized for term in _ENTERPRISE_AUDIT_TERMS)


def agent_request_fingerprint(
    request: AgentRequest,
    access_context: AccessContext,
    mode: AgentMode,
) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "access_role": access_context.role.value,
        "agent_mode": mode.value,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def response_audit_fields(
    response: AgentResponse,
) -> tuple[tuple[str, ...], int, bool]:
    tool_names = tuple(dict.fromkeys(call.tool_name for call in response.tool_calls))
    evidence_ids: list[str] = [item.source_id for item in response.knowledge_evidence]
    if response.report is not None:
        evidence_ids.extend(response.report.data_evidence)
        evidence_ids.extend(response.report.document_evidence)
    analysis = response.analysis
    if analysis is not None:
        evidence_ids.extend(getattr(analysis, "evidence_source_ids", ()) or ())
    return (
        tool_names,
        len(dict.fromkeys(evidence_ids)),
        response.status is AgentTaskStatus.PENDING,
    )


@dataclass
class InMemoryAgentRunStore:
    _records: dict[str, AgentRunRecord] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    def claim(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        mode: AgentMode,
        auditable: bool,
    ) -> AgentRunClaim:
        fingerprint = agent_request_fingerprint(request, access_context, mode)
        with self._lock:
            existing = self._records.get(request.request_id)
            if existing is not None:
                status = (
                    AgentRunClaimStatus.EXISTING
                    if existing.request_fingerprint == fingerprint
                    else AgentRunClaimStatus.CONFLICT
                )
                return AgentRunClaim(status, existing.model_copy(deep=True))
            now = datetime.now(UTC)
            record = AgentRunRecord(
                request_id=request.request_id,
                request_fingerprint=fingerprint,
                conversation_id=request.conversation_id,
                user_id=access_context.user_id,
                access_role=access_context.role,
                agent_mode=mode,
                original_question=request.question,
                auditable=auditable,
                status=AgentTaskStatus.RUNNING,
                created_at=now,
                updated_at=now,
            )
            self._records[request.request_id] = record
            return AgentRunClaim(AgentRunClaimStatus.NEW, record.model_copy(deep=True))

    def complete(self, response: AgentResponse, *, duration_ms: float) -> None:
        with self._lock:
            record = self._require(response.request_id)
            tool_names, evidence_count, approval_required = response_audit_fields(response)
            self._records[response.request_id] = record.model_copy(
                update={
                    "status": response.status,
                    "tool_names": tool_names,
                    "evidence_count": evidence_count,
                    "approval_required": approval_required,
                    "failure_reason": None,
                    "response": response.model_copy(deep=True),
                    "duration_ms": duration_ms,
                    "updated_at": datetime.now(UTC),
                }
            )

    def fail(self, request_id: str, reason: str, *, duration_ms: float) -> None:
        with self._lock:
            record = self._require(request_id)
            self._records[request_id] = record.model_copy(
                update={
                    "status": AgentTaskStatus.FAILED,
                    "failure_reason": reason,
                    "duration_ms": duration_ms,
                    "updated_at": datetime.now(UTC),
                }
            )

    def get(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> AgentRunRecord | None:
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return None
            _check_viewer(record, viewer)
            return record.model_copy(deep=True)

    def _require(self, request_id: str) -> AgentRunRecord:
        try:
            return self._records[request_id]
        except KeyError as exc:
            raise RuntimeError("agent request was not registered") from exc


CLAIM_AGENT_RUN_SQL = """
WITH inserted AS (
    INSERT INTO agent_request_runs (
        request_id, request_fingerprint, conversation_id, user_id,
        access_role, agent_mode, original_question, auditable, status
    )
    VALUES (
        %(request_id)s, %(request_fingerprint)s, %(conversation_id)s,
        %(user_id)s, %(access_role)s, %(agent_mode)s,
        %(original_question)s, %(auditable)s, 'running'
    )
    ON CONFLICT (request_id) DO NOTHING
    RETURNING *
)
SELECT 'new' AS claim_status, inserted.* FROM inserted
UNION ALL
SELECT 'existing' AS claim_status, existing.*
FROM agent_request_runs AS existing
WHERE existing.request_id = %(request_id)s
  AND NOT EXISTS (SELECT 1 FROM inserted)
LIMIT 1;
"""

GET_AGENT_RUN_SQL = """
SELECT * FROM agent_request_runs WHERE request_id = %(request_id)s;
"""

COMPLETE_AGENT_RUN_SQL = """
UPDATE agent_request_runs
SET status = %(status)s,
    tool_names = %(tool_names)s,
    evidence_count = %(evidence_count)s,
    approval_required = %(approval_required)s,
    failure_reason = NULL,
    response_payload = %(response_payload)s,
    duration_ms = %(duration_ms)s,
    updated_at = CURRENT_TIMESTAMP
WHERE request_id = %(request_id)s;
"""

FAIL_AGENT_RUN_SQL = """
UPDATE agent_request_runs
SET status = 'failed',
    failure_reason = %(failure_reason)s,
    duration_ms = %(duration_ms)s,
    updated_at = CURRENT_TIMESTAMP
WHERE request_id = %(request_id)s;
"""


@dataclass(frozen=True)
class DatabaseAgentRunStore:
    def claim(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        mode: AgentMode,
        auditable: bool,
    ) -> AgentRunClaim:
        fingerprint = agent_request_fingerprint(request, access_context, mode)
        params = {
            "request_id": request.request_id,
            "request_fingerprint": fingerprint,
            "conversation_id": request.conversation_id,
            "user_id": access_context.user_id,
            "access_role": access_context.role.value,
            "agent_mode": mode.value,
            "original_question": request.question,
            "auditable": auditable,
        }
        with connect_to_database() as connection:
            row = connection.execute(CLAIM_AGENT_RUN_SQL, params).fetchone()
        if row is None:
            raise RuntimeError("agent request registry did not return a claim")
        record = _record_from_row(row)
        status = AgentRunClaimStatus(row["claim_status"])
        if record.request_fingerprint != fingerprint:
            status = AgentRunClaimStatus.CONFLICT
        return AgentRunClaim(status, record)

    def complete(self, response: AgentResponse, *, duration_ms: float) -> None:
        tool_names, evidence_count, approval_required = response_audit_fields(response)
        params = {
            "request_id": response.request_id,
            "status": response.status.value,
            "tool_names": list(tool_names),
            "evidence_count": evidence_count,
            "approval_required": approval_required,
            "response_payload": Jsonb(response.model_dump(mode="json")),
            "duration_ms": duration_ms,
        }
        with connect_to_database() as connection:
            cursor = connection.execute(COMPLETE_AGENT_RUN_SQL, params)
            if cursor.rowcount != 1:
                raise RuntimeError("agent request was not registered")

    def fail(self, request_id: str, reason: str, *, duration_ms: float) -> None:
        with connect_to_database() as connection:
            cursor = connection.execute(
                FAIL_AGENT_RUN_SQL,
                {
                    "request_id": request_id,
                    "failure_reason": reason,
                    "duration_ms": duration_ms,
                },
            )
            if cursor.rowcount != 1:
                raise RuntimeError("agent request was not registered")

    def get(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> AgentRunRecord | None:
        with connect_to_database() as connection:
            row = connection.execute(
                GET_AGENT_RUN_SQL,
                {"request_id": request_id},
            ).fetchone()
        if row is None:
            return None
        record = _record_from_row(row)
        _check_viewer(record, viewer)
        return record


def _record_from_row(row: dict) -> AgentRunRecord:
    payload = dict(row)
    payload.pop("claim_status", None)
    response_payload = payload.pop("response_payload", None)
    payload["response"] = (
        AgentResponse.model_validate(response_payload)
        if response_payload is not None
        else None
    )
    return AgentRunRecord.model_validate(payload)


def _check_viewer(record: AgentRunRecord, viewer: AccessContext) -> None:
    if viewer.role is not AccessRole.ADMIN and viewer.user_id != record.user_id:
        raise PermissionError("agent request belongs to another user")
