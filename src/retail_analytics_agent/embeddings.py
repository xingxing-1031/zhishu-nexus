from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from retail_analytics_agent.knowledge_chunks import (
    KnowledgeChunk,
    KnowledgeCorpus,
)


class EmbeddingError(RuntimeError):
    """Stable error for unavailable or invalid embedding responses."""


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class _OllamaEmbedResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    embeddings: list[list[float]]


@dataclass(slots=True)
class OllamaEmbeddingProvider:
    client: httpx.Client
    model: str = "bge-m3"

    @property
    def model_id(self) -> str:
        return f"ollama:{self.model}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        input_texts = list(texts)
        if not input_texts:
            return []
        if any(not text.strip() for text in input_texts):
            raise EmbeddingError("embedding input text must not be empty")

        try:
            response = self.client.post(
                "/api/embed",
                json={"model": self.model, "input": input_texts},
            )
            response.raise_for_status()
            embeddings = _OllamaEmbedResponse.model_validate(
                response.json()
            ).embeddings
            _validate_vectors(embeddings, expected_count=len(input_texts))
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise EmbeddingError(f"Ollama embedding failed: {exc}") from exc
        return embeddings


class EmbeddedKnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk: KnowledgeChunk
    embedding: tuple[float, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_finite_vector(self) -> Self:
        if not all(isfinite(value) for value in self.embedding):
            raise ValueError("embedding values must be finite")
        return self


class EmbeddedKnowledgeCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    vector_dimension: int = Field(gt=0)
    chunks: tuple[EmbeddedKnowledgeChunk, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_vectors(self) -> Self:
        dimensions = {len(item.embedding) for item in self.chunks}
        if dimensions != {self.vector_dimension}:
            raise ValueError("all embeddings must match vector_dimension")
        source_ids = [item.chunk.source_id for item in self.chunks]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("embedded chunk source_id values must be unique")
        return self


def embed_knowledge_corpus(
    provider: EmbeddingProvider,
    corpus: KnowledgeCorpus,
) -> EmbeddedKnowledgeCorpus:
    vectors = provider.embed([chunk.content for chunk in corpus.chunks])
    _validate_vectors(vectors, expected_count=len(corpus.chunks))
    embedded_chunks = tuple(
        EmbeddedKnowledgeChunk(chunk=chunk, embedding=tuple(vector))
        for chunk, vector in zip(corpus.chunks, vectors, strict=True)
    )
    return EmbeddedKnowledgeCorpus(
        corpus_id=corpus.corpus_id,
        embedding_model=provider.model_id,
        vector_dimension=len(vectors[0]),
        chunks=embedded_chunks,
    )


def _validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
) -> None:
    if len(vectors) != expected_count:
        raise ValueError(
            f"expected {expected_count} embeddings, received {len(vectors)}"
        )
    if not vectors or not vectors[0]:
        raise ValueError("embedding vectors must not be empty")
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise ValueError("embedding vectors must use one dimension")
    if any(not isfinite(value) for vector in vectors for value in vector):
        raise ValueError("embedding values must be finite")
