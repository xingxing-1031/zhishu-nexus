from __future__ import annotations

from collections.abc import Callable

from retail_analytics_agent.evaluation_executors import (
    AnswerJudge,
    EvaluationCaseWorkflow,
    ObservedWorkflowExecutor,
    ReasonCodeResolver,
)
from retail_analytics_agent.evaluation_runs import EvaluationVariant
from retail_analytics_agent.metric_retrieval import MetricRetriever
from retail_analytics_agent.retrieval_adapters import (
    CatalogEvidenceAdapter,
    EvidenceRetrievalAdapter,
    MetricCandidateEvidenceAdapter,
)


EvaluationWorkflowFactory = Callable[
    [EvidenceRetrievalAdapter],
    EvaluationCaseWorkflow,
]


def create_variant_retrieval_adapters(
    *,
    retrieval_retriever: MetricRetriever,
    reranker_retriever: MetricRetriever,
    candidate_k: int = 5,
) -> dict[EvaluationVariant, EvidenceRetrievalAdapter]:
    """Create the only component that differs across experiment variants."""

    if candidate_k < 1:
        raise ValueError("candidate_k must be positive")
    return {
        EvaluationVariant.BASELINE: CatalogEvidenceAdapter(),
        EvaluationVariant.RETRIEVAL: MetricCandidateEvidenceAdapter(
            metric_retriever=retrieval_retriever,
            candidate_k=candidate_k,
        ),
        EvaluationVariant.RERANKER: MetricCandidateEvidenceAdapter(
            metric_retriever=reranker_retriever,
            candidate_k=candidate_k,
        ),
    }


def create_variant_executors(
    *,
    execution_id: str,
    workflow_factory: EvaluationWorkflowFactory,
    retrieval_retriever: MetricRetriever,
    reranker_retriever: MetricRetriever,
    candidate_k: int = 5,
    reason_code_resolver: ReasonCodeResolver | None = None,
    answer_judge: AnswerJudge | None = None,
) -> dict[EvaluationVariant, ObservedWorkflowExecutor]:
    """Build comparable executors while sharing every non-retrieval dependency."""

    if not execution_id.strip():
        raise ValueError("execution_id must not be blank")
    adapters = create_variant_retrieval_adapters(
        retrieval_retriever=retrieval_retriever,
        reranker_retriever=reranker_retriever,
        candidate_k=candidate_k,
    )
    executors: dict[EvaluationVariant, ObservedWorkflowExecutor] = {}
    for variant, adapter in adapters.items():
        kwargs: dict[str, object] = {
            "variant": variant,
            "workflow": workflow_factory(adapter),
            "execution_id": execution_id,
            "answer_judge": answer_judge,
        }
        if reason_code_resolver is not None:
            kwargs["reason_code_resolver"] = reason_code_resolver
        executors[variant] = ObservedWorkflowExecutor(**kwargs)
    return executors
