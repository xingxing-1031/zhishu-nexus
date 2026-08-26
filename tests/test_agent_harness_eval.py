"""Agent Harness 分层评测：development 与 frozen 数据驱动执行器。

评测纪律（对齐 docs/EVALUATION_PROTOCOL.md 新增小节）：
- development 集用于日常回归调优；
- frozen 集 @pytest.mark.frozen 标记，样本一经消费不得修改语义，
  如需变更必须提升 frozen_version 并在报告中说明。
- 本文件所有探针均为离线确定性契约验证；远程模型端到端 harness 评测
  属于后续工作，不得把本文件结果表述为真实模型效果。

设置环境变量 RUNTIME_EVAL_WRITE_REPORTS=1 时，
会把原始逐例结果写入 evaluation/reports/ 留存。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from retail_analytics_agent.access_control import AccessPolicy, authorize
from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    ContextLayer,
    ContextLayerName,
)
from retail_analytics_agent.agent_runtime import (
    AgentRunBudget,
    AgentRunBudgetExceeded,
    AgentRunDeadlineExceeded,
    AgentRunGuard,
)
from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.checkpoint_meta import (
    CheckpointMeta,
    InMemoryCheckpointMetaStore,
)
from retail_analytics_agent.context_builder import (
    ConservativeTokenCounter,
    content_hash,
    render_layers,
)
from retail_analytics_agent.context_store import (
    ConversationTurn,
    InMemoryConversationStore,
)
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.skills import SkillDefinition, evaluate_completion
from retail_analytics_agent.tracing import classify_error_type

_EVAL_DIR = Path(__file__).parent.parent / "evaluation"
_DEV_CASES = _EVAL_DIR / "agent_harness_development.jsonl"
_FROZEN_CASES = _EVAL_DIR / "agent_harness_frozen.jsonl"

_ALL_LAYERS = {
    "model",
    "context",
    "tool",
    "skill",
    "state",
    "permission",
    "memory",
    "runtime",
}


def _load_cases(path: Path) -> tuple[dict, ...]:
    with path.open(encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle if line.strip())


def _context_layer(item: dict) -> ContextLayer:
    return ContextLayer.model_construct(
        layer=ContextLayerName(item["layer"]),
        source_id=item["source_id"],
        priority=item["priority"],
        content=item["content"],
    )


class _FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def _make_guard(*, deadline_seconds: float = 60.0, **limits: int) -> AgentRunGuard:
    request = AgentRequest(
        request_id="REQ-BUDGET",
        conversation_id="c-budget",
        user_id="USER-001",
        question="预算探针",
    )
    budget = AgentRunBudget(deadline_seconds=deadline_seconds, **limits)
    clock = _FakeClock()
    return AgentRunGuard.create(request, AgentMode.DATA, budget, clock=clock)


def _probe_attribution(case: dict) -> dict:
    category = classify_error_type(
        case["args"].get("error_type"),
        case["args"]["message"],
    )
    assert category is not None, case["case_id"]
    assert category.value == case["expect"]["category"], case["case_id"]
    return {"category": category.value}


def _probe_context_render_order(case: dict) -> dict:
    rendered = render_layers(
        tuple(_context_layer(item) for item in case["args"]["layers"])
    )
    source_ids: list[str] = []
    for line in rendered.splitlines():
        head = line[1 : line.index("]")] if line.startswith("[") else ""
        parts = [part for part in head.split(":") if part]
        source_ids.append(parts[-1])
    assert source_ids == case["expect"]["order_source_ids"], rendered
    return {"rendered_lines": len(source_ids)}


def _probe_context_render_stable_hash(case: dict) -> dict:
    first = content_hash(case["args"]["content"])
    second = content_hash(case["args"]["content"])
    assert first == second
    assert first != content_hash(first + "x")
    counter = ConservativeTokenCounter()
    assert counter.count("") == 0
    assert counter.count("字" * 10) <= counter.count("字" * 40)
    return {"hash_prefix": first[:8]}


def _probe_skill_completion(case: dict) -> dict:
    definition = SkillDefinition.model_construct(
        required_evidence=tuple(case["args"]["required_evidence"])
    )
    outcome = evaluate_completion(
        definition,
        evidence_ids=tuple(case["args"]["evidence_ids"]),
    )
    assert outcome.satisfied == case["expect"]["satisfied"], outcome.missing
    assert sorted(outcome.missing) == sorted(case["expect"].get("missing", ()))
    return {"satisfied": outcome.satisfied}


def _conversation_memory_probe(case: dict) -> dict:
    args = case["args"]
    store = InMemoryConversationStore()
    record = store.create_or_get(args["conversation_id"], args["user_id"])
    for index, turn_args in enumerate(args["turns"], start=1):
        turn = ConversationTurn(
            request_id=f"{args['conversation_id']}-T{index}",
            **turn_args,
        )
        store.append_turn(
            args["conversation_id"],
            args["user_id"],
            turn,
        )
    final = store.get(args["conversation_id"], args["user_id"])
    summary = store.save_summary(
        args["conversation_id"],
        args["user_id"],
        args.get("summary", ""),
    ).summary
    assert final is not None
    assert len(final.turns) == case["expect"]["turns_after_append"]
    assert summary == case["expect"]["summary"]
    assert record is not None
    return {"turns": len(final.turns)}


def _budget_actions_probe(case: dict) -> dict:
    args = case["args"]
    guard = _make_guard(
        max_steps=args.get("max_steps", 8),
        max_model_calls=args.get("max_model_calls", 12),
        max_tool_calls=args.get("max_tool_calls", 16),
        token_budget=args.get("token_budget", 4000),
    )
    with pytest.raises(AgentRunBudgetExceeded) as excinfo:
        for _ in range(args.get("steps_to_take", 0)):
            guard.record_step()
        for _ in range(args.get("calls_to_take", 0)):
            guard.record_model_call()
        for _ in range(args.get("tools_to_take", 0)):
            guard.record_tool_call()
        for _ in range(args.get("calls", 0)):
            guard.record_tokens(args.get("tokens_per_call", 1))
    assert excinfo.value.reason == case["expect"]["raises_reason"], case["case_id"]
    return {"reason": excinfo.value.reason}


def _deadline_probe(case: dict) -> dict:
    args = case["args"]
    clock = _FakeClock()
    guard = _make_guard(deadline_seconds=args["deadline_seconds"])
    guard._clock = clock  # noqa: SLF001 探针需要注入时钟，复用已创建实例
    guard._deadline_monotonic = clock() + args["deadline_seconds"]  # noqa: SLF001
    clock.value += args["clock_advance_seconds"]
    with pytest.raises(AgentRunDeadlineExceeded) as excinfo:
        guard.check()
    return {"reason": excinfo.value.reason}


def _authorize_base(case: dict) -> dict:
    args = case["args"]
    expires_in = args.get("expires_in_seconds")
    policy_kwargs = {}
    if "authorized_datasets" in args:
        policy_kwargs["authorized_datasets"] = frozenset(
            args["authorized_datasets"]
        )
    if expires_in is not None:
        policy_kwargs["expires_at"] = datetime.now(UTC) + timedelta(
            seconds=float(expires_in)
        )
    policy = AccessPolicy(**policy_kwargs) if policy_kwargs else None
    decision = authorize(
        AccessContext(user_id=args.get("user_id", "USER-HARNESS"), role=AccessRole(args["role"])),
        args["action"],
        args["resource"],
        policy=policy,
    )
    assert decision.allowed == case["expect"]["allowed"], (
        f"{args['action']} {args['resource']}: {decision.reason}"
    )
    assert decision.reason == case["expect"]["reason"], decision.reason
    return {"allowed": decision.allowed}


_PROBES = {
    "attribution": _probe_attribution,
    "attribution_unknown_fallback": _probe_attribution,
    "context_render_order": _probe_context_render_order,
    "context_render_stable_hash": _probe_context_render_stable_hash,
    "skill_completion": _probe_skill_completion,
    "authorize": _authorize_base,
    "authorize_expired_policy": _authorize_base,
    "conversation_memory": _conversation_memory_probe,
}


def _run_case(case: dict) -> dict:
    check = case["check"]
    if check.startswith("budget_") and check != "budget_deadline":
        return _budget_actions_probe(case)
    if check == "budget_deadline":
        return _deadline_probe(case)
    if check == "checkpoint_guard":
        return _checkpoint_guard_probe(case)
    probe = _PROBES.get(check)
    if probe is None:
        raise AssertionError(f"未知探针类型: {check}")
    return probe(case)


def _checkpoint_guard_probe(case: dict) -> dict:
    args = case["args"]
    store = InMemoryCheckpointMetaStore()
    store.save(
        CheckpointMeta(
            request_id="REQ-HARNESS",
            user_id=args["meta_user_id"],
            state_version=args["meta_state_version"],
        )
    )
    runner = LangGraphAnalysisRunner(Mock(), checkpoint_meta=store)
    request = AgentRequest(
        request_id="REQ-HARNESS",
        conversation_id="c-harness",
        user_id=args["caller_user_id"],
        question="恢复探针",
        max_rows=10,
    )
    context = AccessContext(user_id=args["caller_user_id"], role=AccessRole.ANALYST)
    with pytest.raises((RuntimeError, PermissionError)) as excinfo:
        runner.run(request, context)
    assert case["expect"]["raises"] in str(excinfo.value), str(excinfo.value)
    return {"error": type(excinfo.value).__name__}


def _write_report(path: Path, cases: tuple[dict, ...], results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "results": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("case", _load_cases(_DEV_CASES), ids=lambda c: c["case_id"])
def test_development_harness_case(case: dict) -> None:
    _run_case(case)


def test_development_set_covers_all_layers() -> None:
    cases = _load_cases(_DEV_CASES)
    layers = {case["layer"] for case in cases}
    assert layers == _ALL_LAYERS, layers


@pytest.mark.frozen
@pytest.mark.parametrize("case", _load_cases(_FROZEN_CASES), ids=lambda c: c["case_id"])
def test_frozen_harness_case(case: dict) -> None:
    _run_case(case)


@pytest.mark.frozen
def test_frozen_set_minimum_coverage() -> None:
    cases = _load_cases(_FROZEN_CASES)
    layers = {case["layer"] for case in cases}
    assert {"permission", "state", "runtime"} <= layers
