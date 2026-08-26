from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
    inject_fault,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
)
from retail_analytics_agent.tracing import (
    InMemoryExecutionTraceStore,
    TraceErrorCategory,
    TraceStatus,
    classify_error,
    classify_error_type,
    execution_trace_context,
    hash_input,
    record_execution_trace,
)
from retail_analytics_agent.workflow import create_initial_state

_REQUEST_ID = "REQ-TRACE-001"


def _initial_state(user_id: str = "USER-001") -> dict:
    return create_initial_state(
        AnalysisRequest(
            request_id=_REQUEST_ID,
            user_id=user_id,
            question="各渠道销售额",
            max_rows=10,
        )
    )


# --- 父子事件链（按 run_id 查看完整链路） -------------------------------


def test_trace_forms_parent_child_chain_by_run_id() -> None:
    store = InMemoryExecutionTraceStore()

    with execution_trace_context(_REQUEST_ID, store, run_id="RUN-X"):
        record_execution_trace(
            "node.plan",
            TraceStatus.STARTED,
            node="plan",
            event_type="node.plan",
        )
        record_execution_trace(
            "node.plan",
            TraceStatus.SUCCEEDED,
            node="plan",
            event_type="node.plan",
        )

    started, succeeded = store.list_for_request(_REQUEST_ID)
    assert started.status is TraceStatus.STARTED
    assert succeeded.status is TraceStatus.SUCCEEDED
    assert started.parent_event_id is None
    assert succeeded.parent_event_id == started.event_id
    assert started.event_id != succeeded.event_id
    assert all(event.run_id == "RUN-X" for event in (started, succeeded))


def test_trace_nested_events_form_hierarchy() -> None:
    store = InMemoryExecutionTraceStore()

    with execution_trace_context(_REQUEST_ID, store, run_id="RUN-Y"):
        record_execution_trace(
            "node.generate_sql",
            TraceStatus.STARTED,
            node="generate_sql",
            event_type="node.generate_sql",
        )
        record_execution_trace(
            "model.llm",
            TraceStatus.STARTED,
            event_type="model.call",
        )
        record_execution_trace(
            "model.llm",
            TraceStatus.SUCCEEDED,
            event_type="model.call",
        )
        record_execution_trace(
            "node.generate_sql",
            TraceStatus.SUCCEEDED,
            node="generate_sql",
            event_type="node.generate_sql",
        )

    node_started, model_started, model_done, node_done = store.list_for_request(
        _REQUEST_ID
    )
    assert node_started.parent_event_id is None
    assert model_started.parent_event_id == node_started.event_id
    assert model_done.parent_event_id == model_started.event_id
    assert node_done.parent_event_id == node_started.event_id


# --- 失败归因元数据 -----------------------------------------------------


def test_failure_event_carries_classification_metadata() -> None:
    store = InMemoryExecutionTraceStore()

    with execution_trace_context(_REQUEST_ID, store):
        record_execution_trace(
            "node.execute_sql",
            TraceStatus.STARTED,
            node="execute_sql",
            event_type="node.execute_sql",
        )
        record_execution_trace(
            "node.execute_sql",
            TraceStatus.FAILED,
            node="execute_sql",
            event_type="node.execute_sql",
            attempt=2,
            error_type="PermissionError",
            error_message="dataset not authorized",
        )

    failed = store.list_for_request(_REQUEST_ID)[-1]
    assert failed.status is TraceStatus.FAILED
    assert failed.component == "node.execute_sql"
    assert failed.node == "execute_sql"
    assert failed.attempt == 2
    assert failed.error_type == "PermissionError"
    assert failed.error_category is TraceErrorCategory.PERMISSION


# --- 固定 8 层错误分类 --------------------------------------------------


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        ("model_timeout", TraceErrorCategory.MODEL),
        ("model_invalid_json", TraceErrorCategory.MODEL),
        ("ModelInvocationError", TraceErrorCategory.MODEL),
        ("tool_timeout", TraceErrorCategory.TOOL),
        ("tool_unauthorized", TraceErrorCategory.TOOL),
        ("SQLSafetyError", TraceErrorCategory.TOOL),
        ("database_unavailable", TraceErrorCategory.TOOL),
        ("permission_denied", TraceErrorCategory.PERMISSION),
        ("PermissionError", TraceErrorCategory.PERMISSION),
        ("ContextBuilderError", TraceErrorCategory.CONTEXT),
        ("SkillExecutionError", TraceErrorCategory.SKILL),
        ("StateValidationError", TraceErrorCategory.STATE),
        ("ConversationStoreError", TraceErrorCategory.MEMORY),
        ("WorkflowDeadlineExceeded", TraceErrorCategory.RUNTIME),
        ("unknown_thing", TraceErrorCategory.RUNTIME),
    ],
)
def test_error_category_mapping_is_fixed(
    error_type: str,
    expected: TraceErrorCategory,
) -> None:
    assert classify_error_type(error_type) is expected


def test_classify_error_from_exception_object() -> None:
    assert classify_error(PermissionError("not authorized")) is (
        TraceErrorCategory.PERMISSION
    )


def test_classify_error_type_with_no_signal_returns_none() -> None:
    assert classify_error_type(None) is None


# --- 固定输入 + 故障规则下可重复 ----------------------------------------


def _run_retrieve_once(store: InMemoryExecutionTraceStore) -> None:
    with execution_trace_context(_REQUEST_ID, store):
        record_execution_trace(
            "node.retrieve",
            TraceStatus.STARTED,
            node="retrieve",
            event_type="node.retrieve",
        )
        try:
            inject_fault("node.retrieve")
        except PermissionError as exc:
            record_execution_trace(
                "node.retrieve",
                TraceStatus.FAILED,
                node="retrieve",
                event_type="node.retrieve",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        else:
            record_execution_trace(
                "node.retrieve",
                TraceStatus.SUCCEEDED,
                node="retrieve",
                event_type="node.retrieve",
            )


def _signature(events) -> tuple[tuple, ...]:
    return tuple(
        (e.component, e.status, e.error_type, e.error_category)
        for e in events
    )


def test_trace_sequence_reproducible_under_fixed_faults() -> None:
    rule = FaultRule("node.retrieve", 1, PermissionError("not authorized"))
    store_a, store_b = InMemoryExecutionTraceStore(), InMemoryExecutionTraceStore()

    with fault_injection_context(ScriptedFaultInjector((rule,))):
        _run_retrieve_once(store_a)
    with fault_injection_context(ScriptedFaultInjector((rule,))):
        _run_retrieve_once(store_b)

    assert _signature(store_a.list_for_request(_REQUEST_ID)) == _signature(
        store_b.list_for_request(_REQUEST_ID)
    )
    assert _signature(store_a.list_for_request(_REQUEST_ID))[1][1] is (
        TraceStatus.FAILED
    )


# --- 脱敏 ---------------------------------------------------------------


def test_record_trace_redacts_secret_keys_in_payload() -> None:
    store = InMemoryExecutionTraceStore()

    with execution_trace_context(_REQUEST_ID, store):
        record_execution_trace(
            "node.plan",
            TraceStatus.STARTED,
            node="plan",
            event_type="node.plan",
            payload={
                "api_key": "sk-abc",
                "password": "pwd",
                "safe": "ok",
                "nested": {"token": "x"},
            },
        )
        record_execution_trace(
            "node.plan",
            TraceStatus.SUCCEEDED,
            node="plan",
            event_type="node.plan",
        )

    payload = store.list_for_request(_REQUEST_ID)[0].payload
    assert payload["api_key"] == "[REDACTED]"
    assert payload["password"] == "[REDACTED]"
    assert payload["safe"] == "ok"
    assert payload["nested"]["token"] == "[REDACTED]"


def test_hash_input_is_stable_content_hash() -> None:
    assert hash_input({"a": 1}) == hash_input({"a": 1})
    assert hash_input({"a": 1}) != hash_input({"a": 2})


# --- 越权查看（既有能力证明） -------------------------------------------


def test_trace_viewer_cannot_see_stranger_full_trace() -> None:
    graph = Mock()
    graph.get_state.return_value = SimpleNamespace(
        values=_initial_state(user_id="USER-001"),
        next=(),
    )
    runner = LangGraphAnalysisRunner(graph, trace_store=InMemoryExecutionTraceStore())

    with pytest.raises(
        PermissionError,
        match="analysis request belongs to another user",
    ):
        runner.get_trace(
            _REQUEST_ID,
            AccessContext(user_id="OTHER", role=AccessRole.ANALYST),
        )
