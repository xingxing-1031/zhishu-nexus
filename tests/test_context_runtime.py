from __future__ import annotations

import json
from unittest.mock import Mock

import httpx

from retail_analytics_agent.agent_models import (
    ContextLayerName,
    ContextSnapshot,
    SkillId,
    Subtask,
    TaskPlan,
    ToolCallRecord,
)
from retail_analytics_agent.context_builder import (
    ContextBuilder,
    content_hash,
    render_context_for_model,
)
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.model_adapters import StructuredResultSummarizer
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
)
from retail_analytics_agent.structured_chat import StructuredChatProtocol
from retail_analytics_agent.workflow import (
    create_initial_state,
    create_summarize_node,
)


def _plan() -> TaskPlan:
    return TaskPlan(
        goal="解释退款率变化",
        skill_id=SkillId.REFUND_DIAGNOSIS,
        subtasks=(Subtask(id="trend", description="查询趋势"),),
        completion_criteria=("有数据证据",),
    )


def _analysis_plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计最近 30 天各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        time_range={"days": 30},
        sort=[{"field": "sales_amount", "direction": "descending"}],
        limit=10,
    )


def _builder() -> ContextBuilder:
    return ContextBuilder(InMemoryConversationStore())


def test_build_creates_five_ordered_layers_with_metadata() -> None:
    snapshot = _builder().build(
        "c1",
        "退款率为什么变化",
        _plan(),
        user_id="u1",
        access_context="analyst",
        evidence=("query:trend",),
        system_rules=("必须基于证据回答",),
        metrics_schema=("退款率=退款单数/订单数",),
        tool_calls=(
            ToolCallRecord(
                request_id="r1",
                tool_name="sql.query",
                input_hash="a" * 64,
                status="succeeded",
                duration_ms=5,
            ),
        ),
    )

    present = (
        ContextLayerName.SYSTEM_RULES,
        ContextLayerName.QUESTION,
        ContextLayerName.METRICS_SCHEMA,
        ContextLayerName.EVIDENCE,
        ContextLayerName.HISTORY,
    )
    first_index = {
        name: next(
            index
            for index, layer in enumerate(snapshot.layers)
            if layer.layer is name
        )
        for name in present
    }
    assert list(first_index.values()) == sorted(first_index.values())

    for layer in snapshot.layers:
        assert layer.source_id
        assert 1 <= layer.priority <= 5
        assert layer.token_cost >= 1
        assert layer.permission_scope == "analyst"
        assert len(layer.content_hash) == 64

    assert snapshot.token_estimation_method == "ConservativeTokenCounter"
    assert snapshot.layers[0].content == "必须基于证据回答"
    assert snapshot.included_hashes


def test_budget_keeps_rules_metrics_and_question_drops_history() -> None:
    store = InMemoryConversationStore()
    builder = ContextBuilder(store)
    for index in range(8):
        builder.append_turn(
            "c1",
            "u1",
            request_id=f"r{index}",
            role="user",
            content="很长的历史对话内容 " * 100,
        )
    snapshot = builder.build(
        "c1",
        "当前问题",
        _plan(),
        user_id="u1",
        system_rules=("必须基于证据回答",),
        metrics_schema=("退款率=退款单数/订单数",),
        evidence=("query:trend",),
        token_budget=256,
    )

    layer_names = {layer.layer for layer in snapshot.layers}
    assert ContextLayerName.SYSTEM_RULES in layer_names
    assert ContextLayerName.QUESTION in layer_names
    assert ContextLayerName.METRICS_SCHEMA in layer_names
    assert ContextLayerName.EVIDENCE in layer_names
    assert ContextLayerName.HISTORY not in layer_names
    assert snapshot.truncated is True
    assert any(
        reason.startswith("budget:") for reason in snapshot.excluded_reasons
    )


def test_evidence_without_permission_is_excluded() -> None:
    snapshot = _builder().build(
        "c1",
        "问题",
        _plan(),
        user_id="u1",
        evidence=("query:allowed", "query:secret", "doc:vip"),
        allowed_evidence=("query:allowed",),
    )

    evidence_sources = {
        layer.source_id
        for layer in snapshot.layers
        if layer.layer is ContextLayerName.EVIDENCE
    }
    assert evidence_sources == {"query:allowed"}
    assert "no_permission:query:secret" in snapshot.excluded_reasons
    assert "no_permission:doc:vip" in snapshot.excluded_reasons
    assert "query:secret" not in snapshot.summary
    assert "doc:vip" not in render_context_for_model(snapshot)


def test_duplicate_evidence_is_deduplicated() -> None:
    snapshot = _builder().build(
        "c1",
        "问题",
        _plan(),
        user_id="u1",
        evidence=("query:same", "query:same"),
    )

    evidence_sources = {
        layer.source_id
        for layer in snapshot.layers
        if layer.layer is ContextLayerName.EVIDENCE
    }
    assert evidence_sources == {"query:same"}
    assert snapshot.evidence_ids == ("query:same",)


def test_same_input_produces_stable_hash_and_render() -> None:
    first = _builder().build(
        "c1",
        "问题",
        _plan(),
        user_id="u1",
        evidence=("query:trend",),
        system_rules=("规则",),
    )
    second = _builder().build(
        "c1",
        "问题",
        _plan(),
        user_id="u1",
        evidence=("query:trend",),
        system_rules=("规则",),
    )

    assert first.included_hashes == second.included_hashes
    assert render_context_for_model(first) == render_context_for_model(second)
    assert content_hash(render_context_for_model(first)) == content_hash(
        render_context_for_model(second)
    )
    for layer in first.layers:
        assert layer.content_hash == content_hash(layer.content)


def test_replaceable_token_counter_is_used() -> None:
    class _FlatCounter:
        def count(self, text: str) -> int:
            return 7

    builder = ContextBuilder(
        InMemoryConversationStore(),
        token_counter=_FlatCounter(),
    )
    snapshot = builder.build("c1", "问题", _plan(), user_id="u1", token_budget=4000)

    assert snapshot.token_estimation_method == "_FlatCounter"
    assert all(layer.token_cost == 7 for layer in snapshot.layers)
    assert snapshot.token_estimate == 7 * len(snapshot.layers)


def test_create_initial_state_restores_context_snapshot() -> None:
    snapshot = _builder().build("c1", "问题", _plan(), user_id="u1")
    request = AnalysisRequest(
        request_id="r1",
        user_id="u1",
        question="问题",
        context_snapshot=snapshot.model_dump(mode="json"),
    )

    state = create_initial_state(request)
    assert isinstance(state["context_snapshot"], ContextSnapshot)
    assert state["context_snapshot"].conversation_id == "c1"


def test_summarize_node_passes_context_snapshot_to_model() -> None:
    snapshot = _builder().build(
        "c1",
        "退款率为什么变化",
        _plan(),
        user_id="u1",
        system_rules=("必须基于证据回答",),
        evidence=("query:trend",),
    )
    model = Mock()
    node = create_summarize_node(model)

    update = node(
        {
            "plan": _analysis_plan(),
            "execution_error": None,
            "query_rows": [{"channel": "jd", "sales_amount": "9000.00"}],
            "question": "退款率为什么变化",
            "dataset_name": None,
            "context_snapshot": snapshot,
        }
    )

    model.summarize.assert_called_once()
    assert model.summarize.call_args.kwargs["context_snapshot"] is snapshot
    assert update["result_status"].value == "succeeded"


def test_summarize_prompt_includes_rendered_context_snapshot() -> None:
    snapshot = _builder().build(
        "c1",
        "退款率为什么变化",
        _plan(),
        user_id="u1",
        system_rules=("必须基于证据回答",),
        evidence=("query:trend",),
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["user_payload"] = json.loads(
            payload["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"answer": "京东渠道销售额为 9000.00 元。"},
                        ensure_ascii=False,
                    )
                }
            },
        )

    client = httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    summarizer = StructuredResultSummarizer(
        client=client,
        protocol=StructuredChatProtocol.OLLAMA,
    )
    summarizer.summarize(
        question="退款率为什么变化",
        plan=_analysis_plan(),
        rows=[{"channel": "jd", "sales_amount": "9000.00"}],
        context_snapshot=snapshot,
    )

    context_text = captured["user_payload"]["context"]
    assert "[system_rules:system_rule:0]" in context_text
    assert "[question:question]" in context_text
    assert "[evidence:query:trend]" in context_text
    assert "必须基于证据回答" in context_text


def test_access_context_round_trip_keeps_identity() -> None:
    access = AccessContext(user_id="u1", role=AccessRole.ANALYST)
    snapshot = ContextBuilder(InMemoryConversationStore()).build(
        "c1", "问题", _plan(), user_id="u1", access_context=access.role.value
    )
    assert snapshot.summary.startswith("access_role=analyst")
