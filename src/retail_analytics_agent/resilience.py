from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from random import random
from time import monotonic, sleep


class WorkflowDeadlineExceeded(TimeoutError):
    """Raised when the active workflow invocation has no time left."""


_ACTIVE_DEADLINE: ContextVar[float | None] = ContextVar(
    "active_workflow_deadline",
    default=None,
)


@contextmanager
def workflow_time_budget(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        raise ValueError("workflow time budget must be positive")

    deadline = monotonic() + seconds
    current = _ACTIVE_DEADLINE.get()
    if current is not None:
        deadline = min(deadline, current)
    token = _ACTIVE_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _ACTIVE_DEADLINE.reset(token)


def remaining_workflow_seconds() -> float | None:
    deadline = _ACTIVE_DEADLINE.get()
    if deadline is None:
        return None
    return max(0.0, deadline - monotonic())


def bounded_timeout_seconds(component_timeout: float) -> float:
    if component_timeout <= 0:
        raise ValueError("component timeout must be positive")
    remaining = remaining_workflow_seconds()
    if remaining is None:
        return component_timeout
    if remaining <= 0:
        raise WorkflowDeadlineExceeded("workflow time budget exhausted")
    return min(component_timeout, remaining)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError(
                "max_backoff_seconds must be at least initial_backoff_seconds"
            )
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")

    def delay_before_attempt(self, next_attempt: int) -> float:
        if next_attempt <= 1:
            return 0.0
        base_delay = min(
            self.initial_backoff_seconds * (2 ** (next_attempt - 2)),
            self.max_backoff_seconds,
        )
        jitter = base_delay * self.jitter_ratio * random()
        return base_delay + jitter


def wait_before_retry(delay_seconds: float) -> None:
    if delay_seconds <= 0:
        return
    remaining = remaining_workflow_seconds()
    if remaining is not None and delay_seconds >= remaining:
        raise WorkflowDeadlineExceeded(
            "workflow time budget exhausted before the next retry"
        )
    sleep(delay_seconds)
