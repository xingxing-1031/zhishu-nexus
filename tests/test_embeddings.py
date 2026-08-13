import json
from collections.abc import Sequence

import httpx
import pytest

from retail_analytics_agent.embeddings import (
    EmbeddingError,
    OllamaEmbeddingProvider,
    embed_knowledge_corpus,
)
from retail_analytics_agent.knowledge_chunks import DEFAULT_KNOWLEDGE_CORPUS


class _FakeEmbeddingProvider:
    model_id = "fake:embedding-v1"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(index), float(len(text))]
            for index, text in enumerate(texts)
        ]


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )


def test_ollama_provider_sends_batch_and_returns_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/embed"
        assert payload == {
            "model": "bge-m3",
            "input": ["销售额", "平均订单金额"],
        }
        return httpx.Response(200, json={"embeddings": [[1, 0], [0, 1]]})

    provider = OllamaEmbeddingProvider(client=_client(handler))

    vectors = provider.embed(["销售额", "平均订单金额"])

    assert provider.model_id == "ollama:bge-m3"
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_ollama_provider_converts_http_and_shape_errors() -> None:
    unavailable = OllamaEmbeddingProvider(
        client=_client(lambda request: httpx.Response(503))
    )
    wrong_count = OllamaEmbeddingProvider(
        client=_client(
            lambda request: httpx.Response(200, json={"embeddings": [[1, 0]]})
        )
    )

    with pytest.raises(EmbeddingError, match="503"):
        unavailable.embed(["销售额"])
    with pytest.raises(EmbeddingError, match="expected 2 embeddings"):
        wrong_count.embed(["销售额", "退款金额"])


def test_ollama_provider_rejects_empty_text_and_mixed_dimensions() -> None:
    provider = OllamaEmbeddingProvider(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"embeddings": [[1, 0], [1, 0, 2]]},
            )
        )
    )

    with pytest.raises(EmbeddingError, match="must not be empty"):
        provider.embed([" "])
    with pytest.raises(EmbeddingError, match="one dimension"):
        provider.embed(["销售额", "退款金额"])


def test_corpus_embedding_preserves_source_and_model_metadata() -> None:
    embedded = embed_knowledge_corpus(
        _FakeEmbeddingProvider(),
        DEFAULT_KNOWLEDGE_CORPUS,
    )

    assert embedded.corpus_id == "retail-knowledge-v1"
    assert embedded.embedding_model == "fake:embedding-v1"
    assert embedded.vector_dimension == 2
    assert len(embedded.chunks) == 14
    assert embedded.chunks[0].chunk.source_id == "metric.sales_amount.v1"
    assert embedded.chunks[0].embedding == (0.0, float(len(embedded.chunks[0].chunk.content)))


def test_corpus_embedding_rejects_provider_count_mismatch() -> None:
    class MissingVectorProvider(_FakeEmbeddingProvider):
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, 0.0]]

    with pytest.raises(ValueError, match="expected 14 embeddings"):
        embed_knowledge_corpus(
            MissingVectorProvider(),
            DEFAULT_KNOWLEDGE_CORPUS,
        )
