import json
from unittest.mock import Mock

import httpx
import pytest

from retail_analytics_agent.metric_domain import (
    DomainGateError,
    DomainGatedMetricRetriever,
    OllamaMetricDomainGate,
)
from retail_analytics_agent.models import AnalysisMetric


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("query", "supported"),
    [("卖了多少钱", True), ("天气怎么样", False)],
)
def test_ollama_domain_gate_returns_structured_decision(
    query: str,
    supported: bool,
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
                    "content": json.dumps({"supported": supported})
                }
            },
        )

    gate = OllamaMetricDomainGate(client=_client(handler))

    assert gate.is_supported(query) is supported


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


def test_domain_gate_stops_unsupported_query_before_retrieval() -> None:
    gate = Mock()
    gate.is_supported.return_value = False
    retriever = Mock()
    gated = DomainGatedMetricRetriever(gate=gate, retriever=retriever)

    assert gated.search("天气怎么样") == ()
    retriever.search.assert_not_called()


def test_domain_gate_forwards_supported_query() -> None:
    gate = Mock()
    gate.is_supported.return_value = True
    retriever = Mock()
    retriever.search.return_value = (AnalysisMetric.SALES_AMOUNT,)
    gated = DomainGatedMetricRetriever(gate=gate, retriever=retriever)

    assert gated.search("卖了多少钱", top_k=2) == (
        AnalysisMetric.SALES_AMOUNT,
    )
    retriever.search.assert_called_once_with("卖了多少钱", top_k=2)


def test_domain_gate_validates_top_k_before_rejection() -> None:
    gate = Mock()
    gate.is_supported.return_value = False
    gated = DomainGatedMetricRetriever(gate=gate, retriever=Mock())

    with pytest.raises(ValueError, match="top_k must be between"):
        gated.search("天气怎么样", top_k=0)

    gate.is_supported.assert_not_called()
