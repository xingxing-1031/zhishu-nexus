from pathlib import Path
from unittest.mock import Mock

import pytest

from retail_analytics_agent.embeddings import (
    EmbeddedKnowledgeChunk,
    EmbeddedKnowledgeCorpus,
)
from retail_analytics_agent.knowledge_chunks import (
    DEFAULT_KNOWLEDGE_CORPUS,
    KnowledgeType,
)
from retail_analytics_agent.knowledge_store import (
    KNOWLEDGE_VECTOR_DIMENSION,
    SEARCH_KNOWLEDGE_CHUNKS_SQL,
    UPSERT_KNOWLEDGE_CHUNK_SQL,
    search_knowledge_chunks,
    upsert_embedded_corpus,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "migrations"
    / "003_knowledge_chunks.sql"
)


def _embedded_corpus(dimension: int = KNOWLEDGE_VECTOR_DIMENSION):
    chunk = DEFAULT_KNOWLEDGE_CORPUS.chunks[0]
    return EmbeddedKnowledgeCorpus(
        corpus_id="retail-knowledge-v1",
        embedding_model="ollama:bge-m3",
        vector_dimension=dimension,
        chunks=(
            EmbeddedKnowledgeChunk(
                chunk=chunk,
                embedding=tuple(0.0 for _ in range(dimension)),
            ),
        ),
    )


def test_migration_uses_fixed_vector_dimension_and_business_constraints() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "embedding VECTOR(1024) NOT NULL" in migration
    assert "source_id TEXT PRIMARY KEY" in migration
    assert "knowledge_type IN ('metric', 'table', 'join')" in migration
    assert "vector_dims(embedding) = 1024" in migration
    assert "CREATE INDEX" in migration
    assert "hnsw" not in migration.lower()
    assert "ivfflat" not in migration.lower()


def test_upsert_preserves_source_version_model_and_content_hash() -> None:
    connection = Mock()
    corpus = _embedded_corpus()

    count = upsert_embedded_corpus(connection, corpus)

    assert count == 1
    sql, params = connection.execute.call_args.args
    assert sql == UPSERT_KNOWLEDGE_CHUNK_SQL
    assert params["source_id"] == "metric.sales_amount.v1"
    assert params["version"] == "v1"
    assert params["embedding_model"] == "ollama:bge-m3"
    assert len(params["content_sha256"]) == 64
    assert params["embedding"].startswith("[0,0,0")


def test_upsert_rejects_an_embedding_model_with_wrong_dimension() -> None:
    connection = Mock()

    with pytest.raises(ValueError, match="must use 1024 dimensions"):
        upsert_embedded_corpus(connection, _embedded_corpus(dimension=2))

    connection.execute.assert_not_called()


def test_search_applies_model_type_threshold_and_top_k() -> None:
    connection = Mock()
    cursor = Mock()
    cursor.fetchall.return_value = [
        {
            "source_id": "metric.sales_amount.v1",
            "knowledge_type": "metric",
            "version": "v1",
            "related_tables": ["orders", "order_items"],
            "content": "销售额",
            "distance": 0.12,
        }
    ]
    connection.execute.return_value = cursor

    results = search_knowledge_chunks(
        connection,
        query_embedding=[0.0] * KNOWLEDGE_VECTOR_DIMENSION,
        embedding_model="ollama:bge-m3",
        top_k=3,
        knowledge_types=[KnowledgeType.METRIC],
        max_distance=0.4,
    )

    assert results[0].source_id == "metric.sales_amount.v1"
    assert results[0].distance == 0.12
    connection.execute.assert_called_once_with(
        SEARCH_KNOWLEDGE_CHUNKS_SQL,
        {
            "query_embedding": "[" + ",".join(["0"] * 1024) + "]",
            "embedding_model": "ollama:bge-m3",
            "knowledge_types": ["metric"],
            "max_distance": 0.4,
            "top_k": 3,
        },
    )


@pytest.mark.parametrize("top_k", [0, 101])
def test_search_rejects_invalid_limits_before_database_access(top_k: int) -> None:
    connection = Mock()

    with pytest.raises(ValueError, match="top_k must be between"):
        search_knowledge_chunks(
            connection,
            query_embedding=[0.0] * KNOWLEDGE_VECTOR_DIMENSION,
            embedding_model="ollama:bge-m3",
            top_k=top_k,
        )

    connection.execute.assert_not_called()
