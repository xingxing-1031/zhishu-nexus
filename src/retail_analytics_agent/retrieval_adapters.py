from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from retail_analytics_agent.metric_retrieval import MetricRetriever
from retail_analytics_agent.models import (
    AnalysisMetric,
    AnalysisPlan,
    RetrievalEvidence,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    RetrievalTool,
)


class EvidenceRetrievalError(ValueError):
    """Raised when a retrieval variant cannot support the plan."""


class EvidenceRetrievalResult(BaseModel):
    """The common output boundary for every retrieval variant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: tuple[RetrievalEvidence, ...]
    candidate_metrics: tuple[AnalysisMetric, ...]


class EvidenceRetrievalAdapter(Protocol):
    def retrieve(
        self,
        *,
        query: str,
        plan: AnalysisPlan,
    ) -> EvidenceRetrievalResult: ...


@dataclass(frozen=True, slots=True)
class CatalogEvidenceAdapter:
    """Baseline adapter using the deterministic plan-to-catalog path."""

    catalog_retriever: RetrievalTool = CatalogRetrievalTool()

    def retrieve(
        self,
        *,
        query: str,
        plan: AnalysisPlan,
    ) -> EvidenceRetrievalResult:
        del query
        evidence = tuple(self.catalog_retriever.retrieve(plan))
        return EvidenceRetrievalResult(
            evidence=evidence,
            candidate_metrics=tuple(plan.metrics),
        )


@dataclass(frozen=True, slots=True)
class MetricCandidateEvidenceAdapter:
    """Adapt keyword, vector, hybrid or reranked metric search to evidence.

    Candidate search is evaluated separately from deterministic schema
    expansion. A plan is rejected here when any required metric was not
    recalled; the catalog retriever then supplies the approved tables and
    JOINs for the metrics that were recalled.
    """

    metric_retriever: MetricRetriever
    catalog_retriever: RetrievalTool = CatalogRetrievalTool()
    candidate_k: int = 5

    def retrieve(
        self,
        *,
        query: str,
        plan: AnalysisPlan,
    ) -> EvidenceRetrievalResult:
        if not query.strip():
            raise EvidenceRetrievalError("query must not be blank")
        if self.candidate_k < 1:
            raise EvidenceRetrievalError("candidate_k must be positive")

        candidates = tuple(
            self.metric_retriever.search(query, top_k=self.candidate_k)
        )
        candidate_set = set(candidates)
        missing = tuple(metric for metric in plan.metrics if metric not in candidate_set)
        if missing:
            names = ", ".join(metric.value for metric in missing)
            raise EvidenceRetrievalError(
                "required metrics were not recalled: " + names
            )

        evidence = tuple(self.catalog_retriever.retrieve(plan))
        return EvidenceRetrievalResult(
            evidence=evidence,
            candidate_metrics=candidates,
        )
