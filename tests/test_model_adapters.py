import json

import httpx
import pytest

from retail_analytics_agent.model_adapters import (
    ModelInvocationError,
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
)
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisPlan,
    RetrievalEvidence,
)
from retail_analytics_agent.resilience import RetryPolicy
from retail_analytics_agent.tracing import (
    InMemoryExecutionTraceStore,
    TraceStatus,
    execution_trace_context,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计最近 30 天各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        time_range={"days": 30},
        sort=[{"field": "sales_amount", "direction": "descending"}],
        limit=10,
    )


def _model_plan_json() -> str:
    return json.dumps(
        {
            "analysis_goal": "统计最近 30 天各渠道销售额",
            "metrics": ["sales_amount"],
            "dimensions": ["channel"],
            "filters": [],
            "time_range_days": 30,
            "sort": [
                {"field": "sales_amount", "direction": "descending"}
            ],
            "limit": 10,
        },
        ensure_ascii=False,
    )


def _evidence() -> list[RetrievalEvidence]:
    return [
        RetrievalEvidence(
            source_id="metric.sales_amount.v1",
            content=(
                "Formula: SUM(order_items.quantity * order_items.unit_price). "
                "Fixed filters: orders.status equals paid."
            ),
        ),
        RetrievalEvidence(
            source_id="schema.join.orders.order_items",
            content="Join orders.order_id = order_items.order_id",
        ),
    ]


def test_ollama_planner_returns_validated_analysis_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3:4b"
        assert payload["think"] is False
        assert payload["format"]["properties"]["limit"]["maximum"] == 10
        assert payload["format"]["properties"]["filters"]["items"][
            "properties"
        ]["field"]["enum"] == [
            "channel",
            "order_status",
            "product_id",
            "category",
            "refund_status",
        ]
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload == {
            "question": "最近30天各渠道销售额是多少？",
            "max_rows": 10,
        }
        return httpx.Response(
            200,
            json={"message": {"content": _model_plan_json()}},
        )

    plan = OllamaAnalysisPlanner(client=_client(handler)).plan(
        "最近30天各渠道销售额是多少？",
        max_rows=10,
    )

    assert plan == _plan()


def test_ollama_planner_rejects_invalid_model_output() -> None:
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": '{"metrics":["unknown"]}'}},
            )
        )
    )

    with pytest.raises(ModelInvocationError, match="invalid analysis plan"):
        planner.plan("查询销售数据", max_rows=10)


def test_ollama_sql_generator_receives_plan_evidence_and_retry_feedback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["analysis_plan"]["metrics"] == ["sales_amount"]
        assert [
            item["source_id"] for item in user_payload["retrieval_evidence"]
        ] == [
            "metric.sales_amount.v1",
            "schema.join.orders.order_items",
        ]
        assert user_payload["previous_validation_error"] == (
            "wildcard columns are not allowed"
        )
        assert user_payload["access_role"] == "analyst"
        assert user_payload["forbidden_columns"] == ["refunds.reason"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "sql": (
                                "SELECT o.channel, "
                                "SUM(oi.quantity * oi.unit_price) AS sales_amount "
                                "FROM orders AS o JOIN order_items AS oi "
                                "ON o.order_id = oi.order_id "
                                "WHERE o.status = 'paid' GROUP BY o.channel"
                            )
                        }
                    )
                }
            },
        )

    sql = OllamaSQLGenerator(client=_client(handler)).generate(
        question="最近30天各渠道销售额是多少？",
        plan=_plan(),
        evidence=_evidence(),
        access_role=AccessRole.ANALYST,
        validation_error="wildcard columns are not allowed",
    )

    assert "SUM(oi.quantity * oi.unit_price)" in sql
    assert "o.status = 'paid'" in sql


def test_ollama_sql_generator_requires_retrieval_evidence() -> None:
    generator = OllamaSQLGenerator(client=_client(lambda request: None))

    with pytest.raises(ValueError, match="retrieval evidence is required"):
        generator.generate(
            question="查询销售额",
            plan=_plan(),
            evidence=[],
            access_role=AccessRole.ANALYST,
        )


def test_ollama_summarizer_uses_real_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["query_rows"] == [
            {"channel": "jd", "sales_amount": "9000.00"}
        ]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"answer": "最近30天，京东渠道销售额为 9000.00 元。"},
                        ensure_ascii=False,
                    )
                }
            },
        )

    answer = OllamaResultSummarizer(client=_client(handler)).summarize(
        question="最近30天各渠道销售额是多少？",
        plan=_plan(),
        rows=[{"channel": "jd", "sales_amount": "9000.00"}],
    )

    assert answer == "最近30天，京东渠道销售额为 9000.00 元。"


def test_ollama_summarizer_rejects_ungrounded_numbers() -> None:
    summarizer = OllamaResultSummarizer(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={
                    "message": {
                        "content": json.dumps(
                            {"answer": "京东渠道销售额为 801.00 元。"},
                            ensure_ascii=False,
                        )
                    }
                },
            )
        )
    )

    with pytest.raises(
        ModelInvocationError,
        match="absent from verified inputs: 801",
    ):
        summarizer.summarize(
            question="最近30天各渠道销售额是多少？",
            plan=_plan(),
            rows=[{"channel": "jd", "sales_amount": "800.00"}],
        )


def test_ollama_planner_retries_transient_http_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            json={"message": {"content": _model_plan_json()}},
        )

    planner = OllamaAnalysisPlanner(
        client=_client(handler),
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
            jitter_ratio=0,
        ),
    )

    assert planner.plan("查询销售额", max_rows=10) == _plan()
    assert attempts == 2


def test_ollama_planner_does_not_retry_permanent_http_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="invalid request")

    planner = OllamaAnalysisPlanner(
        client=_client(handler),
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
            jitter_ratio=0,
        ),
    )

    with pytest.raises(ModelInvocationError, match="HTTP 400"):
        planner.plan("查询销售额", max_rows=10)

    assert attempts == 1


def test_fault_injected_model_retry_records_complete_trace() -> None:
    transport_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(
            200,
            json={"message": {"content": _model_plan_json()}},
        )

    injector = ScriptedFaultInjector(
        (
            FaultRule(
                "model.plan",
                1,
                httpx.ConnectTimeout("injected connection timeout"),
            ),
        )
    )
    trace_store = InMemoryExecutionTraceStore()
    planner = OllamaAnalysisPlanner(
        client=_client(handler),
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
            jitter_ratio=0,
        ),
    )

    with (
        execution_trace_context("REQ-TRACE", trace_store),
        fault_injection_context(injector),
    ):
        assert planner.plan("查询销售额", max_rows=10) == _plan()

    events = trace_store.list_for_request("REQ-TRACE")
    assert [(event.status, event.attempt) for event in events] == [
        (TraceStatus.STARTED, 1),
        (TraceStatus.FAILED, 1),
        (TraceStatus.RETRY_SCHEDULED, 1),
        (TraceStatus.STARTED, 2),
        (TraceStatus.SUCCEEDED, 2),
    ]
    assert events[1].error_type == "ConnectTimeout"
    assert events[2].retry_delay_ms == 0
    assert transport_calls == 1
