from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    MetricCatalog,
)
from retail_analytics_agent.models import AnalysisMetric

MAX_METRIC_RESULTS = 10


class MetricRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> Sequence[AnalysisMetric]: ...


@dataclass(frozen=True, slots=True)
class KeywordMetricRetriever:
    """Transparent baseline that matches literal metric aliases in a query."""

    catalog: MetricCatalog = DEFAULT_METRIC_CATALOG

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]:
        if not 1 <= top_k <= MAX_METRIC_RESULTS:
            raise ValueError(
                f"top_k must be between 1 and {MAX_METRIC_RESULTS}"
            )
        if not query.strip():
            return ()

        normalized_query = query.casefold()
        matches: list[tuple[int, int, AnalysisMetric]] = []
        for catalog_index, definition in enumerate(self.catalog.definitions):
            matched_alias_lengths = [
                len(alias)
                for alias in definition.aliases
                if alias.casefold() in normalized_query
            ]
            if matched_alias_lengths:
                matches.append(
                    (
                        max(matched_alias_lengths),
                        catalog_index,
                        definition.metric,
                    )
                )

        matches.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in matches[:top_k])
