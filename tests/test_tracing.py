from typing import cast

from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
)
from retail_analytics_agent.models import AnalysisResultStatus
from retail_analytics_agent.tracing import (
    ExecutionTraceEvent,
    InMemoryExecutionTraceStore,
    TraceStatus,
    execution_trace_context,
    record_execution_trace,
)
from retail_analytics_agent.workflow import (
    AnalysisState,
    trace_workflow_node,
)


def test_in_memory_trace_store_isolates_requests() -> None:
    store = InMemoryExecutionTraceStore()

    with execution_trace_context("REQ-1", store):
        record_execution_trace("node.plan", TraceStatus.STARTED)
        record_execution_trace(
            "node.plan",
            TraceStatus.SUCCEEDED,
            duration_ms=8,
        )
    with execution_trace_context("REQ-2", store):
        record_execution_trace("node.plan", TraceStatus.STARTED)

    events = store.list_for_request("REQ-1")
    assert [event.status for event in events] == [
        TraceStatus.STARTED,
        TraceStatus.SUCCEEDED,
    ]
    assert events[1].duration_ms == 8


def test_workflow_node_trace_records_execution_failure() -> None:
    store = InMemoryExecutionTraceStore()
    node = trace_workflow_node(
        "execute_sql",
        lambda state: {
            "execution_error": "query timed out",
            "trace": ["execute_sql"],
        },
    )

    with execution_trace_context("REQ-FAIL", store):
        node(cast(AnalysisState, {}))

    assert [event.status for event in store.list_for_request("REQ-FAIL")] == [
        TraceStatus.STARTED,
        TraceStatus.FAILED,
    ]


def test_workflow_node_trace_records_summary_degradation() -> None:
    store = InMemoryExecutionTraceStore()
    node = trace_workflow_node(
        "summarize",
        lambda state: {
            "result_status": AnalysisResultStatus.DEGRADED,
            "trace": ["summarize"],
        },
    )

    with execution_trace_context("REQ-DEGRADED", store):
        node(cast(AnalysisState, {}))

    assert [event.status for event in store.list_for_request("REQ-DEGRADED")] == [
        TraceStatus.STARTED,
        TraceStatus.DEGRADED,
    ]


def test_trace_event_rejects_negative_duration() -> None:
    try:
        ExecutionTraceEvent(
            request_id="REQ-1",
            component="node.plan",
            status=TraceStatus.SUCCEEDED,
            duration_ms=-1,
        )
    except ValueError as exc:
        assert "greater than or equal to 0" in str(exc)
    else:
        raise AssertionError("negative duration was accepted")


def test_trace_store_failure_does_not_break_business_operation() -> None:
    class FailingStore:
        def record(self, event: ExecutionTraceEvent) -> None:
            raise RuntimeError("trace database unavailable")

        def list_for_request(self, request_id: str):
            return ()

    with execution_trace_context("REQ-TRACE-FAIL", FailingStore()):
        record_execution_trace("node.plan", TraceStatus.STARTED)


def test_injected_trace_store_failure_is_fail_open() -> None:
    store = InMemoryExecutionTraceStore()
    injector = ScriptedFaultInjector(
        (
            FaultRule(
                "trace.store",
                1,
                RuntimeError("injected trace failure"),
            ),
        )
    )

    with (
        execution_trace_context("REQ-INJECTED-TRACE", store),
        fault_injection_context(injector),
    ):
        record_execution_trace("node.plan", TraceStatus.STARTED)

    assert store.list_for_request("REQ-INJECTED-TRACE") == ()
