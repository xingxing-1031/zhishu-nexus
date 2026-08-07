import json
from unittest.mock import Mock

import httpx
import pytest

from retail_analytics_agent.metric_domain import (
    DomainDecision,
    DomainGateError,
    DomainGatedMetricRetriever,
    DomainRejectionReason,
    OllamaMetricDomainGate,
    explicit_domain_rejection,
)
from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.structured_chat import StructuredChatProtocol


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("query", "decision"),
    [
        ("卖了多少钱", DomainDecision(supported=True)),
        (
            "天气怎么样",
            DomainDecision(
                supported=False,
                reason_code=DomainRejectionReason.UNSUPPORTED_METRIC,
            ),
        ),
    ],
)
def test_ollama_domain_gate_returns_structured_decision(
    query: str,
    decision: DomainDecision,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["model"] == "qwen3:4b"
        assert payload["think"] is False
        assert json.loads(payload["messages"][1]["content"])["question"] == query
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": decision.model_dump_json()
                }
            },
        )

    gate = OllamaMetricDomainGate(client=_client(handler))

    assert gate.classify(query) == decision


def test_ollama_domain_gate_rejects_invalid_response() -> None:
    gate = OllamaMetricDomainGate(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": "not-json"}},
            )
        )
    )

    with pytest.raises(DomainGateError, match="domain gate failed"):
        gate.is_supported("销售额")


def test_openai_compatible_domain_gate_returns_structured_decision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"supported":true,"reason_code":null}'
                        }
                    }
                ]
            },
        )

    gate = OllamaMetricDomainGate(
        client=_client(handler),
        model="qwen-plus",
        protocol=StructuredChatProtocol.OPENAI_COMPATIBLE,
    )

    assert gate.classify("查询销售额") == DomainDecision(supported=True)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("哪些商品库存快没了", "unsupported_metric"),
        ("各商品毛利润是多少", "unsupported_metric"),
        ("购买用户主要来自哪些年龄段", "unsupported_dimension"),
    ],
)
def test_explicit_domain_policy_rejects_absent_business_concepts(
    query: str,
    reason: str,
) -> None:
    decision = explicit_domain_rejection(query)

    assert decision is not None
    assert decision.supported is False
    assert decision.reason_code is not None
    assert decision.reason_code.value == reason


def test_explicit_domain_policy_does_not_reject_supported_product_units() -> None:
    assert explicit_domain_rejection("最近30天每种商品卖出了多少件") is None


def test_ollama_domain_gate_rejects_inventory_without_model_call() -> None:
    client = _client(lambda request: pytest.fail("model must not be called"))

    decision = OllamaMetricDomainGate(client=client).classify(
        "哪些商品库存快没了"
    )

    assert decision.reason_code is DomainRejectionReason.UNSUPPORTED_METRIC


def test_domain_gate_stops_unsupported_query_before_retrieval() -> None:
    gate = Mock()
    gate.classify.return_value = DomainDecision(
        supported=False,
        reason_code=DomainRejectionReason.UNSUPPORTED_METRIC,
    )
    retriever = Mock()
    gated = DomainGatedMetricRetriever(gate=gate, retriever=retriever)

    assert gated.search("天气怎么样") == ()
    retriever.search.assert_not_called()


def test_domain_gate_forwards_supported_query() -> None:
    gate = Mock()
    gate.classify.return_value = DomainDecision(supported=True)
    retriever = Mock()
    retriever.search.return_value = (AnalysisMetric.SALES_AMOUNT,)
    gated = DomainGatedMetricRetriever(gate=gate, retriever=retriever)

    assert gated.search("卖了多少钱", top_k=2) == (
        AnalysisMetric.SALES_AMOUNT,
    )
    retriever.search.assert_called_once_with("卖了多少钱", top_k=2)


def test_domain_gate_validates_top_k_before_rejection() -> None:
    gate = Mock()
    gate.classify.return_value = DomainDecision(
        supported=False,
        reason_code=DomainRejectionReason.UNSUPPORTED_METRIC,
    )
    gated = DomainGatedMetricRetriever(gate=gate, retriever=Mock())

    with pytest.raises(ValueError, match="top_k must be between"):
        gated.search("天气怎么样", top_k=0)

    gate.classify.assert_not_called()
