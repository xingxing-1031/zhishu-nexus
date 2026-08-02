from __future__ import annotations

from dataclasses import dataclass

from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.embeddings import EmbeddingProvider
from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    MetricCatalog,
)
from retail_analytics_agent.knowledge_chunks import KnowledgeType
from retail_analytics_agent.knowledge_store import (
    KnowledgeSearchResult,
    search_knowledge_chunks,
)
from retail_analytics_agent.metric_retrieval import MAX_METRIC_RESULTS
from retail_analytics_agent.models import AnalysisMetric


@dataclass(frozen=True, slots=True)
class VectorMetricMatch:
    metric: AnalysisMetric
    source_id: str
    distance: float


@dataclass(frozen=True, slots=True)
class VectorMetricRetriever:
    """Retrieves metric candidates from real embeddings stored in pgvector."""

    connection: DatabaseConnection
    provider: EmbeddingProvider
    catalog: MetricCatalog = DEFAULT_METRIC_CATALOG
    max_distance: float | None = None

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]:
        return tuple(
            match.metric
            for match in self.search_with_distances(query, top_k=top_k)
        )

    def search_with_distances(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[VectorMetricMatch, ...]:
        if not 1 <= top_k <= MAX_METRIC_RESULTS:
            raise ValueError(
                f"top_k must be between 1 and {MAX_METRIC_RESULTS}"
            )
        if not query.strip():
            return ()

        vectors = self.provider.embed([query])
        if len(vectors) != 1:
            raise ValueError(
                f"expected 1 query embedding, received {len(vectors)}"
            )
        rows = search_knowledge_chunks(
            self.connection,
            query_embedding=vectors[0],
            embedding_model=self.provider.model_id,
            top_k=top_k,
            knowledge_types=[KnowledgeType.METRIC],
            max_distance=self.max_distance,
        )
        return self._to_matches(rows)

    def _to_matches(
        self,
        rows: list[KnowledgeSearchResult],
    ) -> tuple[VectorMetricMatch, ...]:
        metrics_by_source_id = {
            definition.source_id: definition.metric
            for definition in self.catalog.definitions
        }
        matches: list[VectorMetricMatch] = []
        for row in rows:
            try:
                metric = metrics_by_source_id[row.source_id]
            except KeyError as exc:
                raise ValueError(
                    f"unknown metric source_id returned by vector store: "
                    f"{row.source_id}"
                ) from exc
            matches.append(
                VectorMetricMatch(
                    metric=metric,
                    source_id=row.source_id,
                    distance=row.distance,
                )
            )
        return tuple(matches)
