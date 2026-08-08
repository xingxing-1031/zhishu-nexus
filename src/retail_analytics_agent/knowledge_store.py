from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.embeddings import EmbeddedKnowledgeCorpus
from retail_analytics_agent.knowledge_chunks import KnowledgeType

KNOWLEDGE_VECTOR_DIMENSION = 1024
MAX_KNOWLEDGE_RESULTS = 100

UPSERT_KNOWLEDGE_CHUNK_SQL = """
INSERT INTO knowledge_chunks (
    source_id,
    corpus_id,
    knowledge_type,
    version,
    related_tables,
    content,
    content_sha256,
    embedding_model,
    embedding,
    updated_at
)
VALUES (
    %(source_id)s,
    %(corpus_id)s,
    %(knowledge_type)s,
    %(version)s,
    %(related_tables)s,
    %(content)s,
    %(content_sha256)s,
    %(embedding_model)s,
    %(embedding)s::vector,
    CURRENT_TIMESTAMP
)
ON CONFLICT (source_id) DO UPDATE SET
    corpus_id = EXCLUDED.corpus_id,
    knowledge_type = EXCLUDED.knowledge_type,
    version = EXCLUDED.version,
    related_tables = EXCLUDED.related_tables,
    content = EXCLUDED.content,
    content_sha256 = EXCLUDED.content_sha256,
    embedding_model = EXCLUDED.embedding_model,
    embedding = EXCLUDED.embedding,
    updated_at = CURRENT_TIMESTAMP;
"""

SEARCH_KNOWLEDGE_CHUNKS_SQL = """
SELECT
    source_id,
    knowledge_type,
    version,
    related_tables,
    content,
    embedding <=> %(query_embedding)s::vector AS distance
FROM knowledge_chunks
WHERE embedding_model = %(embedding_model)s
  AND (
      %(knowledge_types)s::text[] IS NULL
      OR knowledge_type = ANY(%(knowledge_types)s::text[])
  )
  AND (
      %(max_distance)s::double precision IS NULL
      OR embedding <=> %(query_embedding)s::vector <= %(max_distance)s
  )
ORDER BY distance, source_id
LIMIT %(top_k)s;
"""


class KnowledgeSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    knowledge_type: KnowledgeType
    version: str | None = None
    related_tables: tuple[str, ...] = Field(min_length=1)
    content: str = Field(min_length=1)
    distance: float = Field(ge=0, le=2)


def upsert_embedded_corpus(
    connection: DatabaseConnection,
    corpus: EmbeddedKnowledgeCorpus,
) -> int:
    if corpus.vector_dimension != KNOWLEDGE_VECTOR_DIMENSION:
        raise ValueError(
            f"knowledge vectors must use {KNOWLEDGE_VECTOR_DIMENSION} dimensions"
        )

    for item in corpus.chunks:
        chunk = item.chunk
        connection.execute(
            UPSERT_KNOWLEDGE_CHUNK_SQL,
            {
                "source_id": chunk.source_id,
                "corpus_id": corpus.corpus_id,
                "knowledge_type": chunk.knowledge_type.value,
                "version": chunk.version,
                "related_tables": list(chunk.related_tables),
                "content": chunk.content,
                "content_sha256": sha256(
                    chunk.content.encode("utf-8")
                ).hexdigest(),
                "embedding_model": corpus.embedding_model,
                "embedding": _vector_literal(item.embedding),
            },
        )
    return len(corpus.chunks)


def search_knowledge_chunks(
    connection: DatabaseConnection,
    *,
    query_embedding: Sequence[float],
    embedding_model: str,
    top_k: int = 5,
    knowledge_types: Sequence[KnowledgeType] | None = None,
    max_distance: float | None = None,
) -> list[KnowledgeSearchResult]:
    if not embedding_model.strip():
        raise ValueError("embedding_model must not be empty")
    if not 1 <= top_k <= MAX_KNOWLEDGE_RESULTS:
        raise ValueError(
            f"top_k must be between 1 and {MAX_KNOWLEDGE_RESULTS}"
        )
    if max_distance is not None and not 0 <= max_distance <= 2:
        raise ValueError("max_distance must be between 0 and 2")
    if len(query_embedding) != KNOWLEDGE_VECTOR_DIMENSION:
        raise ValueError(
            f"query vector must use {KNOWLEDGE_VECTOR_DIMENSION} dimensions"
        )

    rows = connection.execute(
        SEARCH_KNOWLEDGE_CHUNKS_SQL,
        {
            "query_embedding": _vector_literal(query_embedding),
            "embedding_model": embedding_model,
            "knowledge_types": (
                [item.value for item in knowledge_types]
                if knowledge_types is not None
                else None
            ),
            "max_distance": max_distance,
            "top_k": top_k,
        },
    ).fetchall()
    return [KnowledgeSearchResult.model_validate(row) for row in rows]


def _vector_literal(vector: Sequence[float]) -> str:
    if not vector or any(not isfinite(value) for value in vector):
        raise ValueError("vector values must be non-empty and finite")
    return "[" + ",".join(format(value, ".17g") for value in vector) + "]"
