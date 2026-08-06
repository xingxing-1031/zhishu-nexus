from unittest.mock import Mock

import pytest

from retail_analytics_agent.evaluation_runtime import (
    create_shared_metric_retrievers,
)


def test_shared_metric_retrievers_use_the_same_client_and_candidate_budget() -> None:
    client = Mock()
    connection = Mock()

    retrievers = create_shared_metric_retrievers(
        client=client,
        vector_connection=connection,
        embedding_model="bge-m3",
        reranker_model="qwen3:4b",
        candidate_k=4,
    )

    assert retrievers.retrieval.candidate_k == 4
    assert retrievers.reranker.candidate_k == 4
    assert retrievers.reranker.candidate_retriever is retrievers.retrieval
    assert retrievers.retrieval.vector_retriever.connection is connection
    assert retrievers.retrieval.vector_retriever.provider.client is client
    assert retrievers.reranker.reranker.client is client


def test_shared_metric_retrievers_reject_invalid_candidate_budget() -> None:
    with pytest.raises(ValueError, match="candidate_k"):
        create_shared_metric_retrievers(
            client=Mock(),
            vector_connection=Mock(),
            candidate_k=0,
        )
