from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.approval import DatabaseApprovalAuditSink
from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.checkpointing import open_postgres_checkpointer
from retail_analytics_agent.database import DatabaseConnection, connect_to_database
from retail_analytics_agent.embeddings import OllamaEmbeddingProvider
from retail_analytics_agent.evaluation_executors import (
    LangGraphEvaluationCaseWorkflow,
    ObservedWorkflowExecutor,
)
from retail_analytics_agent.evaluation_runs import EvaluationVariant
from retail_analytics_agent.evaluation_variants import create_variant_executors
from retail_analytics_agent.hybrid_metric_retrieval import HybridMetricRetriever
from retail_analytics_agent.metric_reranking import (
    OllamaLLMMetricReranker,
    RerankedMetricRetriever,
)
from retail_analytics_agent.metric_domain import OllamaMetricDomainGate
from retail_analytics_agent.metric_retrieval import KeywordMetricRetriever
from retail_analytics_agent.model_adapters import (
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.resilience import RetryPolicy
from retail_analytics_agent.settings import Settings, get_settings
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever
from retail_analytics_agent.workflow import (
    build_analysis_graph,
    create_workflow_nodes,
)
from retail_analytics_agent.workflow_tools import (
    SafeSQLExecutionTool,
    SQLConsistencyValidationTool,
    SQLGlotValidationTool,
)


@dataclass(frozen=True, slots=True)
class SharedMetricRetrievers:
    retrieval: HybridMetricRetriever
    reranker: RerankedMetricRetriever


def create_shared_metric_retrievers(
    *,
    client: httpx.Client,
    vector_connection: DatabaseConnection,
    embedding_model: str = "bge-m3",
    reranker_model: str = "qwen3:4b",
    candidate_k: int = 5,
    max_distance: float | None = None,
) -> SharedMetricRetrievers:
    if candidate_k < 1:
        raise ValueError("candidate_k must be positive")
    hybrid = HybridMetricRetriever(
        keyword_retriever=KeywordMetricRetriever(),
        vector_retriever=VectorMetricRetriever(
            connection=vector_connection,
            provider=OllamaEmbeddingProvider(
                client=client,
                model=embedding_model,
            ),
            max_distance=max_distance,
        ),
        candidate_k=candidate_k,
    )
    return SharedMetricRetrievers(
        retrieval=hybrid,
        reranker=RerankedMetricRetriever(
            candidate_retriever=hybrid,
            reranker=OllamaLLMMetricReranker(
                client=client,
                model=reranker_model,
            ),
            candidate_k=candidate_k,
        ),
    )


@contextmanager
def open_real_evaluation_executors(
    *,
    execution_id: str,
    settings: Settings | None = None,
    embedding_model: str = "bge-m3",
    reranker_model: str | None = None,
    candidate_k: int = 5,
    max_distance: float | None = None,
) -> Iterator[dict[EvaluationVariant, ObservedWorkflowExecutor]]:
    """Keep all shared real resources open for one controlled experiment."""

    active_settings = settings or get_settings()
    active_reranker_model = reranker_model or active_settings.ollama_model
    retry_policy = RetryPolicy(
        max_attempts=active_settings.model_retry_max_attempts,
        initial_backoff_seconds=(
            active_settings.model_retry_initial_backoff_seconds
        ),
    )
    audit_sink = DatabaseAuditSink()
    approval_audit_sink = DatabaseApprovalAuditSink()

    with (
        httpx.Client(
            base_url=active_settings.ollama_base_url,
            timeout=active_settings.ollama_timeout_seconds,
        ) as client,
        connect_to_database(active_settings) as query_connection,
        connect_to_database(active_settings) as vector_connection,
        open_postgres_checkpointer(active_settings) as checkpointer,
    ):
        retrievers = create_shared_metric_retrievers(
            client=client,
            vector_connection=vector_connection,
            embedding_model=embedding_model,
            reranker_model=active_reranker_model,
            candidate_k=candidate_k,
            max_distance=max_distance,
        )
        planner = OllamaAnalysisPlanner(
            client,
            model=active_settings.ollama_model,
            timeout_seconds=active_settings.ollama_timeout_seconds,
            retry_policy=retry_policy,
        )
        sql_generator = OllamaSQLGenerator(
            client,
            model=active_settings.ollama_model,
            timeout_seconds=active_settings.ollama_timeout_seconds,
            retry_policy=retry_policy,
        )
        summarizer = OllamaResultSummarizer(
            client,
            model=active_settings.ollama_model,
            timeout_seconds=active_settings.ollama_timeout_seconds,
            retry_policy=retry_policy,
        )

        def workflow_factory(retrieval_adapter):
            nodes = create_workflow_nodes(
                domain_gate=OllamaMetricDomainGate(
                    client,
                    model=active_settings.ollama_model,
                ),
                planner=planner,
                retrieval_tool=retrieval_adapter,
                sql_generator=sql_generator,
                validation_tool=SQLGlotValidationTool(audit_sink),
                business_validation_tool=SQLConsistencyValidationTool(),
                approval_audit_sink=approval_audit_sink,
                execution_tool=SafeSQLExecutionTool(
                    query_connection,
                    audit_sink,
                ),
                summarizer=summarizer,
            )
            runner = LangGraphAnalysisRunner(
                build_analysis_graph(nodes, checkpointer=checkpointer),
                workflow_timeout_seconds=(
                    active_settings.workflow_timeout_seconds
                ),
            )
            return LangGraphEvaluationCaseWorkflow(runner)

        yield create_variant_executors(
            execution_id=execution_id,
            workflow_factory=workflow_factory,
            retrieval_retriever=retrievers.retrieval,
            reranker_retriever=retrievers.reranker,
            candidate_k=candidate_k,
        )
