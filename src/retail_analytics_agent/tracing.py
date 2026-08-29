from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import StrEnum
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.fault_injection import inject_fault

logger = logging.getLogger(__name__)


class TraceStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    REJECTED = "rejected"
    PENDING = "pending"
    DEGRADED = "degraded"


class TraceErrorCategory(StrEnum):
    """Fixed eight-layer failure attribution used by Trace events."""

    MODEL = "model"
    CONTEXT = "context"
    TOOL = "tool"
    SKILL = "skill"
    STATE = "state"
    PERMISSION = "permission"
    MEMORY = "memory"
    RUNTIME = "runtime"


# Ordered (substring, category) rules: first hit wins, so specific markers
# must precede generic fallbacks. Keys are casefolded before matching.
_CATEGORY_RULES: tuple[tuple[str, TraceErrorCategory], ...] = (
    # model layer (invocation, response parsing, gateway/timeout)
    ("model_timeout", TraceErrorCategory.MODEL),
    ("model_invalid_json", TraceErrorCategory.MODEL),
    ("model invocation", TraceErrorCategory.MODEL),
    ("modelinvocation", TraceErrorCategory.MODEL),
    ("http_", TraceErrorCategory.MODEL),
    ("httpx", TraceErrorCategory.MODEL),
    ("timeoutexception", TraceErrorCategory.MODEL),
    ("timeouterror", TraceErrorCategory.MODEL),
    ("invalid json", TraceErrorCategory.MODEL),
    ("invalidjson", TraceErrorCategory.MODEL),
    ("response schema", TraceErrorCategory.MODEL),
    # permission layer
    ("permission_denied", TraceErrorCategory.PERMISSION),
    ("permissionerror", TraceErrorCategory.PERMISSION),
    ("not authorized", TraceErrorCategory.PERMISSION),
    ("belongs to another user", TraceErrorCategory.PERMISSION),
    ("only an admin", TraceErrorCategory.PERMISSION),
    ("policy expired", TraceErrorCategory.PERMISSION),
    ("dataset not authorized", TraceErrorCategory.PERMISSION),
    # tool layer (executors, database, sql, retrieval)
    ("tool_timeout", TraceErrorCategory.TOOL),
    ("tool_unauthorized", TraceErrorCategory.TOOL),
    ("sqlsafetyerror", TraceErrorCategory.TOOL),
    ("sql_validation", TraceErrorCategory.TOOL),
    ("sqlvalidation", TraceErrorCategory.TOOL),
    ("sqlbusiness", TraceErrorCategory.TOOL),
    ("catalogretrieval", TraceErrorCategory.TOOL),
    ("table is not allowed", TraceErrorCategory.TOOL),
    ("database_unavailable", TraceErrorCategory.TOOL),
    ("database", TraceErrorCategory.TOOL),
    ("datasource", TraceErrorCategory.TOOL),
    ("toolexecution", TraceErrorCategory.TOOL),
    # context layer
    ("contextbuilder", TraceErrorCategory.CONTEXT),
    ("contextsnapshot", TraceErrorCategory.CONTEXT),
    ("context layer", TraceErrorCategory.CONTEXT),
    ("context rendering", TraceErrorCategory.CONTEXT),
    # skill layer
    ("skill", TraceErrorCategory.SKILL),
    # state layer
    ("state_version", TraceErrorCategory.STATE),
    ("statevalidation", TraceErrorCategory.STATE),
    ("not pending", TraceErrorCategory.STATE),
    ("checkpoint", TraceErrorCategory.STATE),
    # memory layer
    ("conversationstore", TraceErrorCategory.MEMORY),
    ("conversationrecord", TraceErrorCategory.MEMORY),
    ("memory", TraceErrorCategory.MEMORY),
    # runtime layer (budget, deadline, guard, interrupts, unknown)
    ("budget", TraceErrorCategory.RUNTIME),
    ("deadline", TraceErrorCategory.RUNTIME),
    ("runtimeerror", TraceErrorCategory.RUNTIME),
    ("internal", TraceErrorCategory.RUNTIME),
)


def classify_error_type(
    error_type: str | None,
    error_message: str | None = None,
) -> TraceErrorCategory | None:
    """Map an error type/message to one of the eight fixed layers.

    Returns None when there is nothing to classify (no error signal).
    Unknown types fall back to ``runtime`` so every failure is attributable.

    The message is matched before the type name: type names are generic
    containers (``RuntimeError``, ``ValueError``), while the message carries
    the domain signal (``checkpoint``, ``not pending``, ``sql``), so matching
    message first keeps domain-specific attribution accurate.
    """
    signals = (error_message, error_type)
    for text in signals:
        if not text:
            continue
        folded = text.casefold()
        for keyword, category in _CATEGORY_RULES:
            if keyword in folded:
                return category
    return TraceErrorCategory.RUNTIME if (error_type or error_message) else None


def classify_error(exc: BaseException) -> TraceErrorCategory:
    return classify_error_type(type(exc).__name__, str(exc))


def hash_input(obj: Any) -> str:
    """Stable content hash for opaque inputs/outputs recorded in Trace events."""
    payload = json.dumps(
        obj,
        sort_keys=True,
        default=repr,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExecutionTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    request_id: str = Field(min_length=1)
    run_id: str | None = None
    parent_event_id: str | None = None
    component: str = Field(min_length=1)
    node: str | None = None
    event_type: str | None = None
    status: TraceStatus
    attempt: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    duration_ms: int | None = Field(default=None, ge=0)
    input_hash: str | None = None
    output_hash: str | None = None
    context_snapshot_id: str | None = None
    selected_source_ids: tuple[str, ...] | None = None
    tool_name: str | None = None
    tool_args_hash: str | None = None
    policy_decision: str | None = None
    token_usage: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None
    error_category: TraceErrorCategory | None = None
    retry_delay_ms: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] | None = Field(default=None)


class ExecutionTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    events: tuple[ExecutionTraceEvent, ...]


class ExecutionTraceStore(Protocol):
    def record(self, event: ExecutionTraceEvent) -> None: ...

    def list_for_request(
        self,
        request_id: str,
    ) -> tuple[ExecutionTraceEvent, ...]: ...


class InMemoryExecutionTraceStore:
    def __init__(self) -> None:
        self._events: list[ExecutionTraceEvent] = []
        self._lock = Lock()

    def record(self, event: ExecutionTraceEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list_for_request(
        self,
        request_id: str,
    ) -> tuple[ExecutionTraceEvent, ...]:
        with self._lock:
            return tuple(
                event for event in self._events if event.request_id == request_id
            )


TRACE_INSERT_SQL = """
INSERT INTO analysis_trace_events (
    request_id,
    component,
    status,
    attempt,
    occurred_at,
    duration_ms,
    error_type,
    error_message,
    retry_delay_ms,
    payload
)
VALUES (
    %(request_id)s,
    %(component)s,
    %(status)s,
    %(attempt)s,
    %(occurred_at)s,
    %(duration_ms)s,
    %(error_type)s,
    %(error_message)s,
    %(retry_delay_ms)s,
    %(payload)s
);
"""

TRACE_SELECT_SQL = """
SELECT request_id,
       component,
       status,
       attempt,
       occurred_at,
       duration_ms,
       error_type,
       error_message,
       retry_delay_ms,
       payload
FROM analysis_trace_events
WHERE request_id = %(request_id)s
ORDER BY trace_event_id;
"""


class DatabaseExecutionTraceStore:
    def record(self, event: ExecutionTraceEvent) -> None:
        legacy_fields = {
            "request_id",
            "component",
            "status",
            "attempt",
            "occurred_at",
            "duration_ms",
            "error_type",
            "error_message",
            "retry_delay_ms",
            "payload",
        }
        with connect_to_database() as connection:
            params = event.model_dump(mode="json", include=legacy_fields)
            # psycopg does not adapt plain Python mappings to PostgreSQL JSONB.
            params["payload"] = Jsonb(params["payload"]) if params["payload"] is not None else None
            connection.execute(TRACE_INSERT_SQL, params)

    def list_for_request(
        self,
        request_id: str,
    ) -> tuple[ExecutionTraceEvent, ...]:
        with connect_to_database() as connection:
            rows = connection.execute(
                TRACE_SELECT_SQL,
                {"request_id": request_id},
            ).fetchall()
        return tuple(ExecutionTraceEvent.model_validate(row) for row in rows)


_ACTIVE_TRACE: ContextVar[
    tuple[str, str | None, ExecutionTraceStore] | None
] = ContextVar("active_execution_trace", default=None)

# Event-id stack: STARTED pushes, a terminal status pops, so nested events
# record the enclosing event as their parent (LIFO pairing, no recursion).
_TRACE_PARENT_STACK: ContextVar[tuple[str, ...]] = ContextVar(
    "trace_parent_event_stack",
    default=(),
)

_TERMINAL_TRACE_STATUSES: frozenset[TraceStatus] = frozenset(
    {
        TraceStatus.SUCCEEDED,
        TraceStatus.FAILED,
        TraceStatus.PENDING,
        TraceStatus.REJECTED,
    }
)

_SENSITIVE_KEY_HINTS = (
    "token",
    "password",
    "secret",
    "api_key",
    "credential",
    "authorization",
    "cookie",
)


def _redact_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Recursively mask values whose keys hint at secrets."""
    if not isinstance(payload, dict):
        return payload

    def redact(value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v, key) for v in value]
        if isinstance(value, tuple):
            return tuple(redact(v, key) for v in value)
        if any(hint in key.casefold() for hint in _SENSITIVE_KEY_HINTS):
            return "[REDACTED]"
        return value

    return redact(payload, "")


@contextmanager
def execution_trace_context(
    request_id: str,
    store: ExecutionTraceStore | None,
    *,
    run_id: str | None = None,
) -> Iterator[None]:
    if store is None:
        yield
        return
    token = _ACTIVE_TRACE.set((request_id, run_id, store))
    try:
        yield
    finally:
        _ACTIVE_TRACE.reset(token)


def record_execution_trace(
    component: str,
    status: TraceStatus,
    *,
    attempt: int = 1,
    duration_ms: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    retry_delay_ms: int | None = None,
    payload: dict[str, Any] | None = None,
    node: str | None = None,
    event_type: str | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
    context_snapshot_id: str | None = None,
    selected_source_ids: tuple[str, ...] | None = None,
    tool_name: str | None = None,
    tool_args_hash: str | None = None,
    policy_decision: str | None = None,
    token_usage: int | None = None,
    error_category: TraceErrorCategory | None = None,
) -> None:
    active = _ACTIVE_TRACE.get()
    if active is None:
        return
    request_id, run_id, store = active
    stack = _TRACE_PARENT_STACK.get()
    event_id = uuid4().hex
    if error_category is None:
        error_category = classify_error_type(error_type, error_message)
    event = ExecutionTraceEvent(
        event_id=event_id,
        request_id=request_id,
        run_id=run_id,
        parent_event_id=stack[-1] if stack else None,
        component=component,
        node=node,
        event_type=event_type,
        status=status,
        attempt=attempt,
        duration_ms=duration_ms,
        input_hash=input_hash,
        output_hash=output_hash,
        context_snapshot_id=context_snapshot_id,
        selected_source_ids=selected_source_ids,
        tool_name=tool_name,
        tool_args_hash=tool_args_hash,
        policy_decision=policy_decision,
        token_usage=token_usage,
        error_type=error_type,
        error_message=error_message,
        error_category=error_category,
        retry_delay_ms=retry_delay_ms,
        payload=_redact_payload(payload),
    )
    try:
        inject_fault("trace.store")
        store.record(event)
        if status is TraceStatus.STARTED:
            _TRACE_PARENT_STACK.set((*stack, event_id))
        elif status in _TERMINAL_TRACE_STATUSES and stack:
            _TRACE_PARENT_STACK.set(stack[:-1])
    except Exception:
        logger.exception(
            "execution trace write failed for request %s component %s",
            request_id,
            component,
        )
