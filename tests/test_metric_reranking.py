import json
from unittest.mock import Mock

import httpx
import pytest

from retail_analytics_agent.metric_reranking import (
    OllamaLLMMetricReranker,
    RerankedMetricRetriever,
    RerankingError,
)
from retail_analytics_agent.models import AnalysisMetric


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )


def test_ollama_reranker_sends_candidates_and_maps_selected_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["model"] == "qwen3:0.6b"
        assert payload["think"] is False
        assert payload["stream"] is False
        assert payload["format"]["properties"]["selected_source_ids"][
            "maxItems"
        ] == 2
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["question"] == "卖了多少钱"
        assert [item["source_id"] for item in user_payload["candidates"]] == [
            "metric.sales_amount.v1",
            "metric.units_sold.v1",
        ]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"selected_source_ids": ["metric.sales_amount.v1"]}
                    )
                }
            },
        )

    reranker = OllamaLLMMetricReranker(client=_client(handler))

    selected = reranker.rerank(
        "卖了多少钱",
        (AnalysisMetric.SALES_AMOUNT, AnalysisMetric.UNITS_SOLD),
        top_k=2,
    )

    assert selected == (AnalysisMetric.SALES_AMOUNT,)


def test_ollama_reranker_can_reject_out_of_domain_query() -> None:
    reranker = OllamaLLMMetricReranker(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": '{"selected_source_ids": []}'}},
            )
        )
    )

    assert reranker.rerank(
        "天气怎么样",
        (AnalysisMetric.SALES_AMOUNT,),
    ) == ()


def test_ollama_reranker_rejects_invalid_model_output() -> None:
    reranker = OllamaLLMMetricReranker(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={
                    "message": {
                        "content": (
                            '{"selected_source_ids": ["metric.unknown.v1"]}'
                        )
                    }
                },
            )
        )
    )

    with pytest.raises(RerankingError, match="unknown source IDs"):
        reranker.rerank("销售额", (AnalysisMetric.SALES_AMOUNT,))


def test_reranked_retriever_passes_complete_candidates_to_reranker() -> None:
    candidate_retriever = Mock()
    candidate_retriever.search.return_value = (
        AnalysisMetric.SALES_AMOUNT,
        AnalysisMetric.UNITS_SOLD,
    )
    reranker = Mock()
    reranker.rerank.return_value = (AnalysisMetric.SALES_AMOUNT,)
    retriever = RerankedMetricRetriever(
        candidate_retriever=candidate_retriever,
        reranker=reranker,
        candidate_k=5,
    )

    selected = retriever.search("卖了多少钱", top_k=2)

    assert selected == (AnalysisMetric.SALES_AMOUNT,)
    candidate_retriever.search.assert_called_once_with("卖了多少钱", top_k=5)
    reranker.rerank.assert_called_once_with(
        "卖了多少钱",
        (AnalysisMetric.SALES_AMOUNT, AnalysisMetric.UNITS_SOLD),
        top_k=2,
    )
