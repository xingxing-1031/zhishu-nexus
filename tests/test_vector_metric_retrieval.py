from unittest.mock import Mock

import pytest

from retail_analytics_agent.knowledge_store import KNOWLEDGE_VECTOR_DIMENSION
from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever


def _provider() -> Mock:
    provider = Mock()
    provider.model_id = "ollama:bge-m3"
    provider.embed.return_value = [[0.0] * KNOWLEDGE_VECTOR_DIMENSION]
    return provider


def _connection_with_rows(rows: list[dict]) -> Mock:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = rows
    return connection


def test_vector_retriever_embeds_query_and_returns_ranked_metrics() -> None:
    provider = _provider()
    connection = _connection_with_rows(
        [
            {
                "source_id": "metric.sales_amount.v1",
                "knowledge_type": "metric",
                "version": "v1",
                "related_tables": ["orders", "order_items"],
                "content": "销售额",
                "distance": 0.12,
            },
            {
                "source_id": "metric.units_sold.v1",
                "knowledge_type": "metric",
                "version": "v1",
                "related_tables": ["orders", "order_items"],
                "content": "销售件数",
                "distance": 0.2,
            },
        ]
    )
    retriever = VectorMetricRetriever(
        connection=connection,
        provider=provider,
        max_distance=0.5,
    )

    matches = retriever.search_with_distances("卖了多少钱", top_k=2)

    assert [item.metric for item in matches] == [
        AnalysisMetric.SALES_AMOUNT,
        AnalysisMetric.UNITS_SOLD,
    ]
    assert [item.distance for item in matches] == [0.12, 0.2]
    provider.embed.assert_called_once_with(["卖了多少钱"])
    params = connection.execute.call_args.args[1]
    assert params["embedding_model"] == "ollama:bge-m3"
    assert params["knowledge_types"] == ["metric"]
    assert params["max_distance"] == 0.5
    assert params["top_k"] == 2


def test_vector_retriever_skips_embedding_for_blank_query() -> None:
    provider = _provider()
    connection = Mock()
    retriever = VectorMetricRetriever(connection=connection, provider=provider)

    assert retriever.search("  ") == ()
    provider.embed.assert_not_called()
    connection.execute.assert_not_called()


def test_vector_retriever_preserves_candidates_by_default() -> None:
    provider = _provider()
    connection = _connection_with_rows([])
    retriever = VectorMetricRetriever(connection=connection, provider=provider)

    assert retriever.search("卖了多少钱") == ()
    params = connection.execute.call_args.args[1]
    assert params["max_distance"] is None


def test_vector_retriever_rejects_unknown_metric_source() -> None:
    connection = _connection_with_rows(
        [
            {
                "source_id": "metric.unknown.v1",
                "knowledge_type": "metric",
                "version": "v1",
                "related_tables": ["orders"],
                "content": "未知指标",
                "distance": 0.1,
            }
        ]
    )
    retriever = VectorMetricRetriever(
        connection=connection,
        provider=_provider(),
    )

    with pytest.raises(ValueError, match="unknown metric source_id"):
        retriever.search("未知指标")


@pytest.mark.parametrize("top_k", [0, 11])
def test_vector_retriever_validates_top_k(top_k: int) -> None:
    retriever = VectorMetricRetriever(
        connection=Mock(),
        provider=_provider(),
    )

    with pytest.raises(ValueError, match="top_k must be between"):
        retriever.search("销售额", top_k=top_k)
