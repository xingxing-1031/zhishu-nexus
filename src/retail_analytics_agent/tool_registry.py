from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from retail_analytics_agent.agent_models import ToolCallRecord, ToolResult, ToolRisk
from retail_analytics_agent.agent_runtime import record_active_tool_call
from retail_analytics_agent.models import AccessContext, AccessRole


class ToolRegistryError(RuntimeError):
    """Stable error for governed tool invocation failures."""


class ToolPermissionError(ToolRegistryError):
    pass


class ToolTimeoutError(ToolRegistryError):
    pass


class ToolInput(BaseModel):
    # Generic adapters may accept a small structured envelope; concrete tools
    # should provide a stricter input_model when they need field validation.
    model_config = ConfigDict(extra="allow")


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    description: str = Field(min_length=1, max_length=500)
    input_model: type[BaseModel] = ToolInput
    output_model: type[BaseModel] = ToolResult
    required_roles: frozenset[AccessRole] = frozenset(
        {AccessRole.ANALYST, AccessRole.ADMIN}
    )
    risk: ToolRisk = ToolRisk.LOW
    timeout_seconds: float = Field(default=30, gt=0, le=900)
    idempotent: bool = True
    allowed_resources: frozenset[str] = frozenset()
    retry_policy: str = Field(default="none", pattern="^(none|fixed)$")
    preconditions: tuple[str, ...] = Field(default=(), max_length=8)
    postconditions: tuple[str, ...] = Field(default=(), max_length=8)


ToolHandler = Callable[[BaseModel, AccessContext], BaseModel | Mapping[str, Any]]


@dataclass(frozen=True)
class ToolCallOutcome:
    result: ToolResult
    record: ToolCallRecord


@dataclass
class ToolRegistry:
    _specs: dict[str, ToolSpec] = field(default_factory=dict)
    _handlers: dict[str, ToolHandler] = field(default_factory=dict)
    _idempotency: dict[
        tuple[str, str, str], tuple[str, ToolCallOutcome]
    ] = field(default_factory=dict)
    clock: Callable[[], float] = monotonic

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def spec(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ToolRegistryError(f"unknown tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def call(
        self,
        name: str,
        payload: Mapping[str, Any] | BaseModel,
        *,
        access_context: AccessContext,
        request_id: str,
        conversation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolCallOutcome:
        spec = self.spec(name)
        if access_context.role not in spec.required_roles:
            raise ToolPermissionError(f"role {access_context.role.value} cannot call {name}")
        try:
            parsed = payload if isinstance(payload, BaseModel) else spec.input_model.model_validate(payload)
            parsed = spec.input_model.model_validate(parsed)
        except ValidationError as exc:
            raise ToolRegistryError(f"invalid input for {name}: {exc}") from exc
        resource = getattr(parsed, "resource", None)
        if spec.allowed_resources and resource not in spec.allowed_resources:
            raise ToolPermissionError(
                f"resource {resource!r} is not allowed for {name}"
            )
        missing_preconditions = [
            field_name
            for field_name in spec.preconditions
            if getattr(parsed, field_name, None) is None
        ]
        if missing_preconditions:
            raise ToolRegistryError(
                f"precondition not met for {name}: missing "
                + ", ".join(missing_preconditions)
            )
        input_hash = hashlib.sha256(
            json.dumps(parsed.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        cache_key = (name, access_context.user_id, idempotency_key or input_hash)
        if spec.idempotent and cache_key in self._idempotency:
            cached_hash, cached_outcome = self._idempotency[cache_key]
            if cached_hash != input_hash:
                raise ToolRegistryError(
                    f"idempotency key for {name} is bound to different input"
                )
            return cached_outcome

        started = self.clock()
        record_active_tool_call()
        try:
            raw = self._handlers[name](parsed, access_context)
            if isinstance(raw, ToolResult):
                if spec.output_model is not ToolResult:
                    output = spec.output_model.model_validate(raw.payload)
                    result = raw.model_copy(
                        update={"payload": output.model_dump(mode="json")}
                    )
                else:
                    result = raw
            elif isinstance(raw, BaseModel):
                output = spec.output_model.model_validate(raw)
                result = ToolResult(
                    tool_name=name,
                    status="succeeded",
                    payload=output.model_dump(mode="json"),
                )
            elif spec.output_model is ToolResult:
                result = ToolResult(tool_name=name, status="succeeded", payload=dict(raw))
            else:
                output = spec.output_model.model_validate(raw)
                result = ToolResult(
                    tool_name=name,
                    status="succeeded",
                    payload=output.model_dump(mode="json"),
                )
        except ToolTimeoutError:
            raise
        except Exception as exc:
            duration_ms = int((self.clock() - started) * 1000)
            record = ToolCallRecord(
                request_id=request_id,
                conversation_id=conversation_id,
                tool_name=name,
                input_hash=input_hash,
                status="failed",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
            return ToolCallOutcome(
                ToolResult(tool_name=name, status="failed", error=str(exc)),
                record,
            )

        elapsed_seconds = self.clock() - started
        duration_ms = int(elapsed_seconds * 1000)
        if elapsed_seconds > spec.timeout_seconds:
            record = ToolCallRecord(
                request_id=request_id, conversation_id=conversation_id,
                tool_name=name, input_hash=input_hash, status="timeout",
                duration_ms=duration_ms, error_type="ToolTimeoutError",
            )
            raise ToolTimeoutError(f"tool {name} exceeded timeout")
        error_type = None
        if result.status == "succeeded":
            missing_postconditions = [
                field_name
                for field_name in spec.postconditions
                if field_name not in result.payload
            ]
            if missing_postconditions:
                result = ToolResult(
                    tool_name=name,
                    status="failed",
                    error=(
                        "postcondition not met: missing "
                        + ", ".join(missing_postconditions)
                    ),
                )
                error_type = "PostconditionError"
        record = ToolCallRecord(
            request_id=request_id, conversation_id=conversation_id,
            tool_name=name, input_hash=input_hash,
            status=("failed" if error_type else "succeeded"),
            duration_ms=duration_ms,
            error_type=error_type,
        )
        outcome = ToolCallOutcome(result, record)
        if spec.idempotent:
            self._idempotency[cache_key] = (input_hash, outcome)
        return outcome
