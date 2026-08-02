from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    DEFAULT_SCHEMA_CATALOG,
    MetricCatalog,
    SchemaCatalog,
)
from retail_analytics_agent.models import RetrievalEvidence


class KnowledgeType(StrEnum):
    METRIC = "metric"
    TABLE = "table"
    JOIN = "join"


_SOURCE_ID_PREFIXES = {
    KnowledgeType.METRIC: "metric.",
    KnowledgeType.TABLE: "schema.",
    KnowledgeType.JOIN: "schema.join.",
}


class KnowledgeChunk(BaseModel):
    """One complete business-semantic unit prepared for retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    knowledge_type: KnowledgeType
    content: str = Field(min_length=1)
    version: str | None = None
    related_tables: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_chunk_identity(self) -> Self:
        expected_prefix = _SOURCE_ID_PREFIXES[self.knowledge_type]
        if not self.source_id.startswith(expected_prefix):
            raise ValueError(
                f"source_id must start with {expected_prefix}"
            )
        if self.knowledge_type is KnowledgeType.METRIC and self.version is None:
            raise ValueError("metric chunks require a version")
        if self.knowledge_type is not KnowledgeType.METRIC and self.version is not None:
            raise ValueError("only metric chunks can contain a version")
        if len(set(self.related_tables)) != len(self.related_tables):
            raise ValueError("related_tables must not contain duplicates")
        return self

    def to_evidence(self) -> RetrievalEvidence:
        return RetrievalEvidence(source_id=self.source_id, content=self.content)


class KnowledgeCorpus(BaseModel):
    """Versionable set of semantic chunks used by retrieval strategies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: str = Field(min_length=1)
    chunks: tuple[KnowledgeChunk, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_source_ids(self) -> Self:
        source_ids = [chunk.source_id for chunk in self.chunks]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("knowledge chunk source_id values must be unique")
        return self


def build_knowledge_corpus(
    metric_catalog: MetricCatalog = DEFAULT_METRIC_CATALOG,
    schema_catalog: SchemaCatalog = DEFAULT_SCHEMA_CATALOG,
    *,
    corpus_id: str = "retail-knowledge-v1",
) -> KnowledgeCorpus:
    chunks: list[KnowledgeChunk] = []

    for definition in metric_catalog.definitions:
        evidence = definition.to_evidence()
        chunks.append(
            KnowledgeChunk(
                source_id=evidence.source_id,
                knowledge_type=KnowledgeType.METRIC,
                content=evidence.content,
                version=definition.version,
                related_tables=definition.source_tables,
            )
        )

    for table in schema_catalog.tables:
        evidence = table.to_evidence()
        chunks.append(
            KnowledgeChunk(
                source_id=evidence.source_id,
                knowledge_type=KnowledgeType.TABLE,
                content=evidence.content,
                related_tables=(table.table_name,),
            )
        )

    for join in schema_catalog.joins:
        evidence = join.to_evidence()
        chunks.append(
            KnowledgeChunk(
                source_id=evidence.source_id,
                knowledge_type=KnowledgeType.JOIN,
                content=evidence.content,
                related_tables=(join.left_table, join.right_table),
            )
        )

    return KnowledgeCorpus(corpus_id=corpus_id, chunks=tuple(chunks))


DEFAULT_KNOWLEDGE_CORPUS = build_knowledge_corpus()
