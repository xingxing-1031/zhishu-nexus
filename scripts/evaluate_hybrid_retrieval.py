from pathlib import Path

import httpx

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.embeddings import OllamaEmbeddingProvider
from retail_analytics_agent.hybrid_metric_retrieval import HybridMetricRetriever
from retail_analytics_agent.metric_retrieval import KeywordMetricRetriever
from retail_analytics_agent.metric_retrieval_evaluation import (
    evaluate_metric_queries,
    load_metric_query_evaluation_suite,
    write_metric_query_evaluation_report,
)
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_SUITE_PATH = PROJECT_ROOT / "evaluation" / "metric_query_gold.json"
REPORT_DIRECTORY = PROJECT_ROOT / "evaluation" / "reports"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "bge-m3"


def main() -> None:
    suite = load_metric_query_evaluation_suite(GOLD_SUITE_PATH)
    with (
        httpx.Client(base_url=OLLAMA_BASE_URL, timeout=120) as client,
        connect_to_database() as connection,
    ):
        retriever = HybridMetricRetriever(
            keyword_retriever=KeywordMetricRetriever(),
            vector_retriever=VectorMetricRetriever(
                connection=connection,
                provider=OllamaEmbeddingProvider(
                    client=client,
                    model=EMBEDDING_MODEL,
                ),
            ),
        )
        for top_k in (1, 5):
            report = evaluate_metric_queries(
                retriever,
                suite,
                top_k=top_k,
            )
            write_metric_query_evaluation_report(
                report,
                REPORT_DIRECTORY / f"hybrid_metric_top{top_k}.json",
            )
            print(
                f"Hybrid Top-{top_k}: "
                f"precision={report.mean_precision_at_k:.3f}, "
                f"recall={report.mean_recall_at_k:.3f}, "
                f"exact_match={report.exact_match_rate:.3f}, "
                f"empty_accuracy={report.empty_query_accuracy:.3f}"
            )


if __name__ == "__main__":
    main()
