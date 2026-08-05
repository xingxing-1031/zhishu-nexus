from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import StrEnum
import logging
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.database import connect_to_database


logger = logging.getLogger(__name__)


class TraceStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    REJECTED = "rejected"
    PENDING = "pending"
    DEGRADED = "degraded"


class ExecutionTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    component: str = Field(min_length=1)
    status: TraceStatus
    attempt: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    duration_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None
    retry_delay_ms: int | None = Field(default=None, ge=0)


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
    retry_delay_ms
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
    %(retry_delay_ms)s
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
       retry_delay_ms
FROM analysis_trace_events
WHERE request_id = %(request_id)s
ORDER BY trace_event_id;
"""


class DatabaseExecutionTraceStore:
    def record(self, event: ExecutionTraceEvent) -> None:
        with connect_to_database() as connection:
            connection.execute(
                TRACE_INSERT_SQL,
                event.model_dump(mode="json"),
            )

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
    tuple[str, ExecutionTraceStore] | None
] = ContextVar("active_execution_trace", default=None)


@contextmanager
def execution_trace_context(
    request_id: str,
    store: ExecutionTraceStore | None,
) -> Iterator[None]:
    if store is None:
        yield
        return
    token = _ACTIVE_TRACE.set((request_id, store))
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
) -> None:
    active = _ACTIVE_TRACE.get()
    if active is None:
        return
    request_id, store = active
    try:
        store.record(
            ExecutionTraceEvent(
                request_id=request_id,
                component=component,
                status=status,
                attempt=attempt,
                duration_ms=duration_ms,
                error_type=error_type,
                error_message=error_message,
                retry_delay_ms=retry_delay_ms,
            )
        )
    except Exception:
        logger.exception(
            "execution trace write failed for request %s component %s",
            request_id,
            component,
        )
