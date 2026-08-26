from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from time import monotonic
from typing import Callable, Iterator
from uuid import uuid4

from pydantic import Field

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentStrictModel,
    AgentTaskStatus,
)


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


class AgentRuntimeErrorKind(StrEnum):
    """Stable failure classification used by Trace and failure attribution."""

    MODEL_TIMEOUT = "model_timeout"
    MODEL_INVALID_JSON = "model_invalid_json"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_UNAUTHORIZED = "tool_unauthorized"
    DATABASE_UNAVAILABLE = "database_unavailable"
    PERMISSION_DENIED = "permission_denied"
    BUDGET_EXCEEDED = "budget_exceeded"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INTERNAL_ERROR = "internal_error"


class AgentRun(AgentStrictModel):
    run_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    mode: AgentMode
    state_version: int = Field(default=1, ge=1)
    started_at: datetime
    deadline: datetime
    status: AgentRunStatus = AgentRunStatus.RUNNING
    terminal_reason: str | None = Field(default=None, max_length=500)
    step_count: int = Field(default=0, ge=0)
    model_call_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    token_budget: int = Field(ge=256, le=32000)
    token_usage: int = Field(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class AgentRunBudget:
    max_steps: int = 8
    max_model_calls: int = 12
    max_tool_calls: int = 16
    deadline_seconds: float = 120.0
    token_budget: int = 4000


class AgentRunHalt(Exception):
    """Runtime control flow exception that should stop the run gracefully."""

    def __init__(
        self,
        message: str,
        *,
        status: AgentRunStatus,
        reason: str,
    ) -> None:
        self.status = status
        self.reason = reason
        super().__init__(message)


class AgentRunBudgetExceeded(AgentRunHalt):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(
            f"agent run exceeded budget limit: {reason}",
            status=AgentRunStatus.BUDGET_EXCEEDED,
            reason=reason,
        )


class AgentRunDeadlineExceeded(AgentRunHalt):
    def __init__(self) -> None:
        super().__init__(
            "agent run exceeded total deadline",
            status=AgentRunStatus.BUDGET_EXCEEDED,
            reason="deadline_exceeded",
        )


def idempotency_key(request_id: str, phase: str) -> str:
    return f"{request_id}:{phase}"


def map_run_status_to_task_status(status: AgentRunStatus) -> AgentTaskStatus:
    if status is AgentRunStatus.SUCCEEDED:
        return AgentTaskStatus.SUCCEEDED
    if status is AgentRunStatus.PARTIAL_SUCCESS:
        return AgentTaskStatus.DEGRADED
    if status is AgentRunStatus.WAITING_APPROVAL:
        return AgentTaskStatus.PENDING
    if status is AgentRunStatus.CANCELLED:
        return AgentTaskStatus.REFUSED
    if status is AgentRunStatus.BUDGET_EXCEEDED:
        return AgentTaskStatus.DEGRADED
    return AgentTaskStatus.FAILED


def map_task_status_to_run_status(status: AgentTaskStatus) -> AgentRunStatus:
    if status is AgentTaskStatus.SUCCEEDED:
        return AgentRunStatus.SUCCEEDED
    if status is AgentTaskStatus.DEGRADED:
        return AgentRunStatus.PARTIAL_SUCCESS
    if status is AgentTaskStatus.PENDING:
        return AgentRunStatus.WAITING_APPROVAL
    if status is AgentTaskStatus.REFUSED:
        return AgentRunStatus.CANCELLED
    return AgentRunStatus.FAILED


class AgentRunGuard:
    """Process-local runtime boundary enforcing deadline and budget limits."""

    def __init__(
        self,
        run: AgentRun,
        budget: AgentRunBudget,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._run = run
        self._budget = budget
        self._clock = clock
        self._deadline_monotonic = clock() + budget.deadline_seconds
        self._lock = RLock()

    @classmethod
    def create(
        cls,
        request: AgentRequest,
        mode: AgentMode,
        budget: AgentRunBudget,
        *,
        run_id: str | None = None,
        thread_id: str | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> AgentRunGuard:
        now = datetime.now(UTC)
        deadline = now + timedelta(seconds=budget.deadline_seconds)
        run = AgentRun(
            run_id=run_id or uuid4().hex,
            request_id=request.request_id,
            thread_id=thread_id or request.conversation_id,
            user_id=request.user_id,
            mode=mode,
            started_at=now,
            deadline=deadline,
            token_budget=budget.token_budget,
        )
        return cls(run, budget, clock=clock)

    @property
    def run(self) -> AgentRun:
        with self._lock:
            return self._run

    @property
    def step_count(self) -> int:
        return self._run.step_count

    @property
    def model_call_count(self) -> int:
        return self._run.model_call_count

    @property
    def tool_call_count(self) -> int:
        return self._run.tool_call_count

    @property
    def token_usage(self) -> int:
        return self._run.token_usage

    def check(self) -> AgentRun:
        with self._lock:
            if self._clock() > self._deadline_monotonic:
                raise AgentRunDeadlineExceeded()
            self._raise_if_budget_exceeded()
            return self._run

    def record_step(self) -> AgentRun:
        with self._lock:
            self._bump(step_count=self._run.step_count + 1)
            return self._run

    def record_model_call(self) -> AgentRun:
        with self._lock:
            self._bump(model_call_count=self._run.model_call_count + 1)
            return self._run

    def record_tool_call(self) -> AgentRun:
        with self._lock:
            self._bump(tool_call_count=self._run.tool_call_count + 1)
            return self._run

    def record_tokens(self, estimate: int) -> AgentRun:
        if estimate < 0:
            raise ValueError("token estimate must be non-negative")
        with self._lock:
            self._bump(token_usage=self._run.token_usage + estimate)
            return self._run

    def finish(
        self,
        status: AgentRunStatus,
        *,
        reason: str | None = None,
    ) -> AgentRun:
        with self._lock:
            self._run = self._run.model_copy(
                update={"status": status, "terminal_reason": reason}
            )
            return self._run

    def _bump(self, **changes: object) -> None:
        if self._clock() > self._deadline_monotonic:
            raise AgentRunDeadlineExceeded()
        self._run = self._run.model_copy(update=changes)
        self._raise_if_budget_exceeded()

    def _raise_if_budget_exceeded(self) -> None:
        if self._run.step_count > self._budget.max_steps:
            raise AgentRunBudgetExceeded(reason="step_limit")
        if self._run.model_call_count > self._budget.max_model_calls:
            raise AgentRunBudgetExceeded(reason="model_call_limit")
        if self._run.tool_call_count > self._budget.max_tool_calls:
            raise AgentRunBudgetExceeded(reason="tool_call_limit")
        if self._run.token_usage > self._budget.token_budget:
            raise AgentRunBudgetExceeded(reason="token_budget")


_ACTIVE_GUARD: ContextVar[AgentRunGuard | None] = ContextVar(
    "active_agent_run_guard",
    default=None,
)


@contextmanager
def agent_run_context(guard: AgentRunGuard) -> Iterator[None]:
    token = _ACTIVE_GUARD.set(guard)
    try:
        yield
    finally:
        _ACTIVE_GUARD.reset(token)


def active_run_guard() -> AgentRunGuard | None:
    return _ACTIVE_GUARD.get()


def record_active_model_call() -> None:
    guard = _ACTIVE_GUARD.get()
    if guard is not None:
        guard.record_model_call()


def record_active_tool_call() -> None:
    guard = _ACTIVE_GUARD.get()
    if guard is not None:
        guard.record_tool_call()
