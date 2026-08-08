from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from retail_analytics_agent.metric_retrieval import (
    MAX_METRIC_RESULTS,
    KeywordMetricRetriever,
)
from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever

DEFAULT_RRF_CONSTANT = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[AnalysisMetric]],
    *,
    top_k: int = 5,
    rrf_constant: int = DEFAULT_RRF_CONSTANT,
) -> tuple[AnalysisMetric, ...]:
    """Merge heterogeneous rankings without comparing their raw scores."""

    if not 1 <= top_k <= MAX_METRIC_RESULTS:
        raise ValueError(
            f"top_k must be between 1 and {MAX_METRIC_RESULTS}"
        )
    if rrf_constant < 1:
        raise ValueError("rrf_constant must be positive")

    scores: dict[AnalysisMetric, float] = {}
    first_seen: dict[AnalysisMetric, int] = {}
    seen_order = 0
    for ranking in rankings:
        seen_in_ranking: set[AnalysisMetric] = set()
        for rank, metric in enumerate(ranking, start=1):
            if metric in seen_in_ranking:
                continue
            seen_in_ranking.add(metric)
            if metric not in first_seen:
                first_seen[metric] = seen_order
                seen_order += 1
            scores[metric] = scores.get(metric, 0.0) + 1 / (
                rrf_constant + rank
            )

    ranked = sorted(
        scores,
        key=lambda metric: (-scores[metric], first_seen[metric]),
    )
    return tuple(ranked[:top_k])


@dataclass(frozen=True, slots=True)
class HybridMetricRetriever:
    keyword_retriever: KeywordMetricRetriever
    vector_retriever: VectorMetricRetriever
    candidate_k: int = 5
    rrf_constant: int = DEFAULT_RRF_CONSTANT

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]:
        if not 1 <= self.candidate_k <= MAX_METRIC_RESULTS:
            raise ValueError(
                f"candidate_k must be between 1 and {MAX_METRIC_RESULTS}"
            )
        keyword_ranking = self.keyword_retriever.search(
            query,
            top_k=self.candidate_k,
        )
        vector_ranking = self.vector_retriever.search(
            query,
            top_k=self.candidate_k,
        )
        return reciprocal_rank_fusion(
            (keyword_ranking, vector_ranking),
            top_k=top_k,
            rrf_constant=self.rrf_constant,
        )
