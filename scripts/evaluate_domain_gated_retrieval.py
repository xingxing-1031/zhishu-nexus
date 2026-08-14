from argparse import ArgumentParser
from pathlib import Path

import httpx

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.embeddings import OllamaEmbeddingProvider
from retail_analytics_agent.hybrid_metric_retrieval import HybridMetricRetriever
from retail_analytics_agent.metric_domain import (
    DomainGatedMetricRetriever,
    OllamaMetricDomainGate,
)
from retail_analytics_agent.metric_reranking import (
    OllamaLLMMetricReranker,
    RerankedMetricRetriever,
)
from retail_analytics_agent.metric_retrieval import KeywordMetricRetriever
from retail_analytics_agent.metric_retrieval_evaluation import (
    evaluate_metric_queries,
    load_metric_query_evaluation_suite,
    write_metric_query_evaluation_report,
)
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever

PROJECT_ROOT = Path(__file__).resolve().parents[1]
def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--suite",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "metric_query_gold.json",
    )
    args = parser.parse_args()
    suite = load_metric_query_evaluation_suite(args.suite)
    with (
        httpx.Client(base_url="http://127.0.0.1:11434", timeout=120) as client,
        connect_to_database() as connection,
    ):
        hybrid = HybridMetricRetriever(
            keyword_retriever=KeywordMetricRetriever(),
            vector_retriever=VectorMetricRetriever(
                connection=connection,
                provider=OllamaEmbeddingProvider(client=client, model="bge-m3"),
                max_distance=None,
            ),
        )
        reranked = RerankedMetricRetriever(
            candidate_retriever=hybrid,
            reranker=OllamaLLMMetricReranker(client=client, model="qwen3:4b"),
        )
        retriever = DomainGatedMetricRetriever(
            gate=OllamaMetricDomainGate(client=client, model="qwen3:4b"),
            retriever=reranked,
        )
        report = evaluate_metric_queries(retriever, suite, top_k=5)

    report_path = (
        PROJECT_ROOT
        / "evaluation"
        / "reports"
        / f"domain_gated_{args.suite.stem}_qwen3_4b.json"
    )
    write_metric_query_evaluation_report(report, report_path)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
