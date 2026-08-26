from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from retail_analytics_agent.agent_models import ToolResult, ToolRisk
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.tool_registry import (
    ToolInput,
    ToolPermissionError,
    ToolRegistry,
    ToolRegistryError,
    ToolSpec,
    ToolTimeoutError,
)


class _ResourceInput(ToolInput):
    resource: str = Field(min_length=1, max_length=40)


class _PayloadInput(ToolInput):
    resource: str = Field(default="internal", max_length=40)
    dataset_id: str | None = Field(default=None, max_length=80)


class _StrictOutput(BaseModel):
    content: str


def _context(role: AccessRole = AccessRole.ANALYST) -> AccessContext:
    return AccessContext(user_id="u1", role=role)


def _registry(spec: ToolSpec, handler) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(spec, handler)
    return registry


def test_contract_ok_when_input_resource_and_output_are_valid() -> None:
    registry = _registry(
        ToolSpec(
            name="demo.query",
            description="demo",
            input_model=_ResourceInput,
            allowed_resources=frozenset({"internal"}),
            preconditions=("resource",),
            postconditions=("rows",),
            risk=ToolRisk.LOW,
        ),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.query",
            status="succeeded",
            payload={"rows": [{"channel": "jd"}]},
        ),
    )
    outcome = registry.call(
        "demo.query",
        {"resource": "internal"},
        access_context=_context(),
        request_id="r1",
    )
    assert outcome.result.status == "succeeded"
    assert outcome.record.status == "succeeded"
    assert outcome.result.payload == {"rows": [{"channel": "jd"}]}


def test_unknown_tool_is_rejected_before_invocation() -> None:
    registry = _registry(
        ToolSpec(name="demo.query", description="demo", input_model=_ResourceInput),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.query", status="succeeded", payload={}
        ),
    )
    with pytest.raises(ToolRegistryError, match="unknown tool"):
        registry.call("missing", {}, access_context=_context(), request_id="r1")


def test_unauthorized_role_is_rejected_before_handler() -> None:
    called = False

    def handler(parsed, ctx):
        nonlocal called
        called = True
        return {"ok": True}

    registry = _registry(
        ToolSpec(
            name="demo.export",
            description="demo",
            input_model=_ResourceInput,
            required_roles=frozenset({AccessRole.ADMIN}),
            risk=ToolRisk.HIGH,
        ),
        handler,
    )
    with pytest.raises(ToolPermissionError, match="cannot call"):
        registry.call(
            "demo.export",
            {"resource": "internal"},
            access_context=_context(),
            request_id="r1",
        )
    assert called is False


def test_resource_outside_allowed_set_is_rejected() -> None:
    registry = _registry(
        ToolSpec(
            name="demo.query",
            description="demo",
            input_model=_ResourceInput,
            allowed_resources=frozenset({"internal"}),
        ),
        lambda parsed, ctx: {"ok": True},
    )
    with pytest.raises(ToolPermissionError, match="not allowed"):
        registry.call(
            "demo.query",
            {"resource": "external"},
            access_context=_context(),
            request_id="r1",
        )


def test_missing_precondition_field_is_rejected() -> None:
    registry = _registry(
        ToolSpec(
            name="demo.query",
            description="demo",
            input_model=_PayloadInput,
            preconditions=("dataset_id",),
        ),
        lambda parsed, ctx: {"ok": True},
    )
    with pytest.raises(ToolRegistryError, match="precondition not met"):
        registry.call(
            "demo.query",
            {"resource": "internal"},
            access_context=_context(),
            request_id="r1",
        )


def test_missing_postcondition_yields_failed_result() -> None:
    registry = _registry(
        ToolSpec(
            name="demo.export",
            description="demo",
            input_model=_ResourceInput,
            postconditions=("markdown",),
        ),
        lambda parsed, ctx: {"ok": True},
    )
    outcome = registry.call(
        "demo.export",
        {"resource": "internal"},
        access_context=_context(),
        request_id="r1",
    )
    assert outcome.result.status == "failed"
    assert "postcondition not met" in (outcome.result.error or "")
    assert outcome.record.status == "failed"
    assert outcome.record.error_type == "PostconditionError"


def test_output_not_matching_schema_yields_failed_result() -> None:
    registry = _registry(
        ToolSpec(
            name="demo.strict",
            description="demo",
            input_model=_ResourceInput,
            output_model=_StrictOutput,
        ),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.strict",
            status="succeeded",
            payload={"other": "value"},
        ),
    )
    outcome = registry.call(
        "demo.strict",
        {"resource": "internal"},
        access_context=_context(),
        request_id="r1",
    )
    assert outcome.result.status == "failed"
    assert outcome.record.error_type == "ValidationError"


def test_timeout_is_classified_for_contract_tool() -> None:
    ticks = iter((0.0, 1.0))
    registry = ToolRegistry(clock=lambda: next(ticks))
    registry.register(
        ToolSpec(
            name="demo.slow",
            description="demo",
            input_model=_ResourceInput,
            timeout_seconds=0.01,
        ),
        lambda parsed, ctx: {"ok": True},
    )
    with pytest.raises(ToolTimeoutError, match="exceeded timeout"):
        registry.call(
            "demo.slow",
            {"resource": "internal"},
            access_context=_context(),
            request_id="r1",
        )


def test_failed_handler_result_is_not_reclassified_by_postconditions() -> None:
    registry = _registry(
        ToolSpec(
            name="demo.failing",
            description="demo",
            input_model=_ResourceInput,
            postconditions=("markdown",),
        ),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.failing",
            status="failed",
            error="service unavailable",
        ),
    )
    outcome = registry.call(
        "demo.failing",
        {"resource": "internal"},
        access_context=_context(),
        request_id="r1",
    )
    assert outcome.result.status == "failed"
    assert outcome.result.error == "service unavailable"
