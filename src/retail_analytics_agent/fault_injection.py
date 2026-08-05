from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Protocol


class FaultInjector(Protocol):
    def raise_if_scheduled(self, component: str) -> None: ...


@dataclass(frozen=True, slots=True)
class FaultRule:
    component: str
    occurrence: int
    error: Exception

    def __post_init__(self) -> None:
        if not self.component.strip():
            raise ValueError("fault component must not be empty")
        if self.occurrence < 1:
            raise ValueError("fault occurrence must be positive")


class ScriptedFaultInjector:
    """Inject deterministic test failures at named component boundaries."""

    def __init__(self, rules: tuple[FaultRule, ...]) -> None:
        keys = [(rule.component, rule.occurrence) for rule in rules]
        if len(keys) != len(set(keys)):
            raise ValueError("fault rules must target unique occurrences")
        self._rules = {
            (rule.component, rule.occurrence): rule.error for rule in rules
        }
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def raise_if_scheduled(self, component: str) -> None:
        with self._lock:
            self._counts[component] += 1
            occurrence = self._counts[component]
            error = self._rules.get((component, occurrence))
        if error is not None:
            raise error

    def calls_for(self, component: str) -> int:
        with self._lock:
            return self._counts[component]


_ACTIVE_FAULT_INJECTOR: ContextVar[FaultInjector | None] = ContextVar(
    "active_fault_injector",
    default=None,
)


@contextmanager
def fault_injection_context(
    injector: FaultInjector | None,
) -> Iterator[None]:
    token = _ACTIVE_FAULT_INJECTOR.set(injector)
    try:
        yield
    finally:
        _ACTIVE_FAULT_INJECTOR.reset(token)


def inject_fault(component: str) -> None:
    injector = _ACTIVE_FAULT_INJECTOR.get()
    if injector is not None:
        injector.raise_if_scheduled(component)
