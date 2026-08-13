import pytest

from retail_analytics_agent.agent_models import (
    SkillId,
    Subtask,
    TaskPlan,
    ToolCallRecord,
)
from retail_analytics_agent.context_builder import ContextBuilder, estimate_tokens
from retail_analytics_agent.context_store import (
    ContextStoreError,
    InMemoryConversationStore,
)


def _plan() -> TaskPlan:
    return TaskPlan(
        goal="解释退款率变化",
        skill_id=SkillId.REFUND_DIAGNOSIS,
        subtasks=(Subtask(id="trend", description="查询趋势"),),
        completion_criteria=("有数据证据",),
    )


def test_store_isolates_users_with_same_conversation_id() -> None:
    store = InMemoryConversationStore()
    builder = ContextBuilder(store)
    builder.append_turn("c1", "u1", request_id="r1", role="user", content="华东")

    assert store.get("c1", "u2") is None
    assert store.get("c1", "u1").turns[0].content == "华东"


def test_confirmed_constraints_are_inherited() -> None:
    store = InMemoryConversationStore()
    builder = ContextBuilder(store)
    builder.append_turn(
        "c1", "u1", request_id="r1", role="user", content="看退款",
        confirmed_constraints=("region=华东",),
    )
    snapshot = builder.build("c1", "继续分析", _plan(), user_id="u1")

    assert "region=华东" in snapshot.confirmed_constraints
    assert "region=华东" in snapshot.summary


def test_question_is_packed_as_one_context_line() -> None:
    snapshot = ContextBuilder(InMemoryConversationStore()).build(
        "c1", "退款率变化", _plan(), user_id="u1",
    )

    assert "question=退款率变化" in snapshot.summary.splitlines()
    assert "q" not in snapshot.summary.splitlines()


def test_context_keeps_evidence_before_old_history_when_budget_is_tight() -> None:
    store = InMemoryConversationStore()
    builder = ContextBuilder(store)
    for index in range(10):
        builder.append_turn(
            "c1", "u1", request_id=f"r{index}", role="user",
            content="很长的历史问题 " * 40,
        )
    snapshot = builder.build(
        "c1", "当前问题", _plan(), user_id="u1",
        evidence=("query:trend", "policy:v1"), token_budget=300,
    )

    assert snapshot.evidence_ids == ("query:trend", "policy:v1")
    assert snapshot.truncated is True
    assert "evidence=query:trend" in snapshot.summary
    assert estimate_tokens(snapshot.summary) <= 300


def test_context_rejects_budget_that_cannot_fit_current_goal() -> None:
    builder = ContextBuilder(InMemoryConversationStore())
    with pytest.raises(ValueError, match="too small"):
        builder.build("c1", "问题", _plan(), user_id="u1", token_budget=1)


def test_store_rejects_blank_identity() -> None:
    with pytest.raises(ContextStoreError):
        InMemoryConversationStore().create_or_get("", "u1")


def test_tool_results_are_bounded_to_recent_calls() -> None:
    builder = ContextBuilder(InMemoryConversationStore())
    calls = tuple(
        ToolCallRecord(
            request_id=f"r{i}", tool_name="sql", input_hash="a" * 64,
            status="succeeded", duration_ms=i,
        )
        for i in range(12)
    )
    snapshot = builder.build(
        "c1", "问题", _plan(), user_id="u1", tool_calls=calls,
    )
    assert len(snapshot.recent_tool_results) == 8
    assert "1ms" not in snapshot.recent_tool_results[0]
