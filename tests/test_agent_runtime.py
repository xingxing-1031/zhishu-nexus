from __future__ import annotations

from typing import Callable

import pytest

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentTaskStatus,
    ToolResult,
)
from retail_analytics_agent.agent_runtime import (
    AgentRunBudget,
    AgentRunBudgetExceeded,
    AgentRunDeadlineExceeded,
    AgentRunGuard,
    AgentRunStatus,
    active_run_guard,
    agent_run_context,
    idempotency_key,
    map_run_status_to_task_status,
    map_task_status_to_run_status,
    record_active_model_call,
    record_active_tool_call,
)
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.tool_registry import ToolInput, ToolRegistry, ToolSpec


class _EchoInput(ToolInput):
    value: str


class _FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._index = 0

    def __call__(self) -> float:
        if self._index >= len(self._values):
            return self._values[-1]
        value = self._values[self._index]
        self._index += 1
        return value


def _request(question: str = "最近30天退款率为什么变化？") -> AgentRequest:
    return AgentRequest(
        request_id="REQ-RT-001",
        conversation_id="CONV-RT-001",
        user_id="USER-001",
        question=question,
        max_rows=10,
        token_budget=4000,
    )


def _access(
    user_id: str = "USER-001",
    role: AccessRole = AccessRole.ANALYST,
) -> AccessContext:
    return AccessContext(user_id=user_id, role=role)


def _guard(
    request: AgentRequest | None = None,
    *,
    budget: AgentRunBudget | None = None,
    clock: Callable[[], float] | None = None,
) -> AgentRunGuard:
    return AgentRunGuard.create(
        request or _request(),
        AgentMode.DATA,
        budget or AgentRunBudget(),
        clock=clock or (lambda: 0.0),
    )


def test_agent_run_guard_builds_full_runtime_metadata() -> None:
    request = _request()
    guard = _guard(request)
    run = guard.run

    assert run.run_id
    assert run.request_id == "REQ-RT-001"
    assert run.thread_id == "CONV-RT-001"
    assert run.user_id == "USER-001"
    assert run.mode is AgentMode.DATA
    assert run.state_version == 1
    assert run.status is AgentRunStatus.RUNNING
    assert run.deadline > run.started_at
    assert run.step_count == 0
    assert run.model_call_count == 0
    assert run.tool_call_count == 0
    assert run.token_budget == 4000
    assert run.token_usage == 0


def test_guard_tracks_step_model_tool_and_token_counts() -> None:
    guard = _guard()
    guard.record_step()
    guard.record_model_call()
    guard.record_model_call()
    guard.record_tool_call()
    guard.record_tokens(1500)

    assert guard.step_count == 1
    assert guard.model_call_count == 2
    assert guard.tool_call_count == 1
    assert guard.token_usage == 1500


@pytest.mark.parametrize(
    ("method", "limit", "reason"),
    [
        ("record_step", 1, "step_limit"),
        ("record_model_call", 1, "model_call_limit"),
        ("record_tool_call", 1, "tool_call_limit"),
    ],
)
def test_guard_exceeds_call_limit(
    method: str,
    limit: int,
    reason: str,
) -> None:
    budget = AgentRunBudget(
        max_steps=limit,
        max_model_calls=limit,
        max_tool_calls=limit,
        deadline_seconds=60,
        token_budget=4000,
    )
    guard = _guard(budget=budget)
    getattr(guard, method)()
    with pytest.raises(AgentRunBudgetExceeded) as excinfo:
        getattr(guard, method)()
    assert excinfo.value.status is AgentRunStatus.BUDGET_EXCEEDED
    assert excinfo.value.reason == reason


def test_guard_exceeds_token_budget() -> None:
    budget = AgentRunBudget(token_budget=400, deadline_seconds=60)
    guard = _guard(budget=budget)
    guard.record_tokens(400)
    with pytest.raises(AgentRunBudgetExceeded) as excinfo:
        guard.record_tokens(1)
    assert excinfo.value.reason == "token_budget"


def test_guard_rejects_negative_token_estimate() -> None:
    guard = _guard()
    with pytest.raises(ValueError):
        guard.record_tokens(-1)


def test_guard_raises_deadline_exceeded() -> None:
    clock = _FakeClock([0.0, 2.0])
    budget = AgentRunBudget(deadline_seconds=1.0)
    guard = _guard(budget=budget, clock=clock)
    with pytest.raises(AgentRunDeadlineExceeded):
        guard.check()
    assert guard.run.status is AgentRunStatus.RUNNING


def test_guard_check_ok_before_deadline() -> None:
    clock = _FakeClock([0.0, 0.0])
    budget = AgentRunBudget(deadline_seconds=1.0)
    guard = _guard(budget=budget, clock=clock)
    guard.check()
    assert guard.run.status is AgentRunStatus.RUNNING


def test_guard_finish_sets_terminal_state() -> None:
    guard = _guard()
    guard.finish(AgentRunStatus.PARTIAL_SUCCESS, reason="knowledge degraded")
    assert guard.run.status is AgentRunStatus.PARTIAL_SUCCESS
    assert guard.run.terminal_reason == "knowledge degraded"


def test_idempotency_key_is_stable_and_scoped() -> None:
    assert idempotency_key("REQ-1", "sql") == "REQ-1:sql"
    assert idempotency_key("REQ-1", "sql") == idempotency_key("REQ-1", "sql")
    assert idempotency_key("REQ-1", "sql") != idempotency_key("REQ-1", "knowledge")


def test_run_status_mapping_round_trip() -> None:
    assert (
        map_run_status_to_task_status(AgentRunStatus.SUCCEEDED)
        is AgentTaskStatus.SUCCEEDED
    )
    assert (
        map_run_status_to_task_status(AgentRunStatus.PARTIAL_SUCCESS)
        is AgentTaskStatus.DEGRADED
    )
    assert (
        map_run_status_to_task_status(AgentRunStatus.WAITING_APPROVAL)
        is AgentTaskStatus.PENDING
    )
    assert (
        map_run_status_to_task_status(AgentRunStatus.CANCELLED)
        is AgentTaskStatus.REFUSED
    )
    assert (
        map_run_status_to_task_status(AgentRunStatus.BUDGET_EXCEEDED)
        is AgentTaskStatus.DEGRADED
    )
    assert (
        map_run_status_to_task_status(AgentRunStatus.FAILED)
        is AgentTaskStatus.FAILED
    )

    assert (
        map_task_status_to_run_status(AgentTaskStatus.SUCCEEDED)
        is AgentRunStatus.SUCCEEDED
    )
    assert (
        map_task_status_to_run_status(AgentTaskStatus.DEGRADED)
        is AgentRunStatus.PARTIAL_SUCCESS
    )
    assert (
        map_task_status_to_run_status(AgentTaskStatus.PENDING)
        is AgentRunStatus.WAITING_APPROVAL
    )
    assert (
        map_task_status_to_run_status(AgentTaskStatus.REFUSED)
        is AgentRunStatus.CANCELLED
    )
    assert (
        map_task_status_to_run_status(AgentTaskStatus.FAILED)
        is AgentRunStatus.FAILED
    )


def test_active_recording_is_noop_without_guard() -> None:
    assert active_run_guard() is None
    record_active_model_call()
    record_active_tool_call()


def test_active_recording_counts_inside_guard_context() -> None:
    guard = _guard()
    with agent_run_context(guard):
        record_active_model_call()
        record_active_tool_call()
    assert guard.model_call_count == 1
    assert guard.tool_call_count == 1


def test_tool_registry_records_active_run_tool_call() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="demo.echo", description="echo"),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.echo",
            status="succeeded",
            payload={"value": parsed.value},
        ),
    )
    guard = _guard()
    with agent_run_context(guard):
        outcome = registry.call(
            "demo.echo",
            {"value": "hello"},
            access_context=_access(),
            request_id="REQ-RT-001",
            conversation_id="CONV-RT-001",
        )
    assert guard.tool_call_count == 1
    assert outcome.record.status == "succeeded"
    assert outcome.result.payload == {"value": "hello"}


def test_tool_registry_idempotent_replay_counts_toward_budget() -> None:
    """幂等重放也计入工具调用预算：预算约束的是执行尝试次数，不能被缓存绕过。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="demo.echo", description="echo"),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.echo",
            status="succeeded",
            payload={"value": parsed.value},
        ),
    )
    guard = _guard()
    with agent_run_context(guard):
        registry.call(
            "demo.echo",
            {"value": "same"},
            access_context=_access(),
            request_id="REQ-RT-001",
            conversation_id="CONV-RT-001",
        )
        registry.call(
            "demo.echo",
            {"value": "same"},
            access_context=_access(),
            request_id="REQ-RT-001",
            conversation_id="CONV-RT-001",
        )
    assert guard.tool_call_count == 2


def test_tool_registry_replay_loop_hits_tool_call_budget() -> None:
    """同一个幂等工具的无限重放必须被预算熔断，而不是静默绕过预算。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="demo.echo", description="echo"),
        lambda parsed, ctx: ToolResult(
            tool_name="demo.echo",
            status="succeeded",
            payload={"value": parsed.value},
        ),
    )
    guard = _guard(budget=AgentRunBudget(max_tool_calls=3))
    with (
        agent_run_context(guard),
        pytest.raises(AgentRunBudgetExceeded) as excinfo,
    ):
        for _ in range(10):
            registry.call(
                "demo.echo",
                {"value": "same"},
                access_context=_access(),
                request_id="REQ-RT-001",
                conversation_id="CONV-RT-001",
            )
    assert excinfo.value.reason == "tool_call_limit"
    assert guard.tool_call_count == 4


def test_end_to_end_normal_run_records_full_counts() -> None:
    guard = AgentRunGuard.create(
        _request(),
        AgentMode.DATA,
        AgentRunBudget(max_steps=8, max_model_calls=12, max_tool_calls=16),
    )
    with agent_run_context(guard):
        guard.record_step()
        record_active_model_call()
        record_active_model_call()
        guard.record_tool_call()
        guard.record_step()
        guard.record_tokens(1200)
    guard.finish(AgentRunStatus.SUCCEEDED)

    run = guard.run
    assert run.status is AgentRunStatus.SUCCEEDED
    assert run.step_count == 2
    assert run.model_call_count == 2
    assert run.tool_call_count == 1
    assert run.token_usage == 1200


def test_end_to_end_budget_exceeded_halts_at_limit() -> None:
    guard = _guard(
        budget=AgentRunBudget(
            max_steps=8,
            max_model_calls=12,
            max_tool_calls=2,
            deadline_seconds=60,
            token_budget=4000,
        )
    )
    with agent_run_context(guard):
        guard.record_step()
        guard.record_tool_call()
        guard.record_tool_call()
        with pytest.raises(AgentRunBudgetExceeded) as excinfo:
            guard.record_tool_call()
    assert excinfo.value.reason == "tool_call_limit"

    guard.finish(excinfo.value.status, reason=excinfo.value.reason)
    assert guard.run.status is AgentRunStatus.BUDGET_EXCEEDED
    assert guard.run.terminal_reason == "tool_call_limit"


def test_same_request_replay_reuses_idempotent_key() -> None:
    from retail_analytics_agent.agent_runs import (
        AgentRunClaimStatus,
        InMemoryAgentRunStore,
        is_auditable_agent_request,
    )

    store = InMemoryAgentRunStore()
    first = store.claim(_request(), _access(), AgentMode.DATA, True)
    replay = store.claim(_request(), _access(), AgentMode.DATA, True)
    assert first.status is AgentRunClaimStatus.NEW
    assert replay.status is AgentRunClaimStatus.EXISTING
    assert replay.record.request_id == first.record.request_id
    assert is_auditable_agent_request(_request().question, AgentMode.DATA)
