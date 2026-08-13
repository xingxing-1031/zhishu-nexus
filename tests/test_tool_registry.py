import time

import pytest
from pydantic import Field

from retail_analytics_agent.agent_models import ToolRisk
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.tool_registry import (
    ToolInput,
    ToolPermissionError,
    ToolRegistry,
    ToolRegistryError,
    ToolSpec,
    ToolTimeoutError,
)


class QueryInput(ToolInput):
    query: str = Field(min_length=1)


def _context(role: AccessRole = AccessRole.ANALYST) -> AccessContext:
    return AccessContext(user_id="u1", role=role)


def test_registry_validates_input_and_unknown_tools() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="sql.query", description="query", input_model=QueryInput),
        lambda payload, context: {"rows": [payload.query]},
    )
    with pytest.raises(ToolRegistryError, match="unknown tool"):
        registry.call("missing", {}, access_context=_context(), request_id="r1")
    with pytest.raises(ToolRegistryError, match="invalid input"):
        registry.call("sql.query", {}, access_context=_context(), request_id="r1")


def test_registry_enforces_role_before_handler() -> None:
    called = False

    def handler(payload, context):
        nonlocal called
        called = True
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="report.export", description="export", input_model=QueryInput,
            required_roles=frozenset({AccessRole.ADMIN}), risk=ToolRisk.HIGH,
        ),
        handler,
    )
    with pytest.raises(ToolPermissionError):
        registry.call("report.export", {"query": "x"}, access_context=_context(), request_id="r1")
    assert called is False


def test_registry_records_failure_and_supports_idempotency() -> None:
    calls = 0

    def handler(payload, context):
        nonlocal calls
        calls += 1
        return {"value": payload.query}

    registry = ToolRegistry()
    registry.register(ToolSpec(name="sql.query", description="query", input_model=QueryInput), handler)
    first = registry.call("sql.query", {"query": "select 1"}, access_context=_context(), request_id="r1", idempotency_key="k1")
    second = registry.call("sql.query", {"query": "select 1"}, access_context=_context(), request_id="r1", idempotency_key="k1")
    assert calls == 1
    assert first.record.input_hash == second.record.input_hash


def test_registry_classifies_handler_failure() -> None:
    registry = ToolRegistry()
    registry.register(ToolSpec(name="sql.query", description="query", input_model=QueryInput), lambda p, c: 1 / 0)
    outcome = registry.call("sql.query", {"query": "x"}, access_context=_context(), request_id="r1")
    assert outcome.result.status == "failed"
    assert outcome.record.error_type == "ZeroDivisionError"


def test_registry_classifies_timeout_after_handler_returns() -> None:
    registry = ToolRegistry()

    def slow(payload, context):
        time.sleep(0.01)
        return {"value": payload.query}

    registry.register(ToolSpec(name="sql.query", description="query", input_model=QueryInput, timeout_seconds=0.001), slow)
    with pytest.raises(ToolTimeoutError, match="exceeded timeout"):
        registry.call("sql.query", {"query": "x"}, access_context=_context(), request_id="r1")
