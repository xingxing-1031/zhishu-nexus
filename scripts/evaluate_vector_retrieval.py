from pathlib import Path

import httpx

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.embeddings import OllamaEmbeddingProvider
from retail_analytics_agent.metric_retrieval_evaluation import (
    evaluate_metric_queries,
    load_metric_query_evaluation_suite,
    write_metric_query_evaluation_report,
)
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_SUITE_PATH = PROJECT_ROOT / "evaluation" / "metric_query_gold.json"
REPORT_PATH = (
    PROJECT_ROOT / "evaluation" / "reports" / "vector_metric_baseline.json"
)
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "bge-m3"


def main() -> None:
    suite = load_metric_query_evaluation_suite(GOLD_SUITE_PATH)
    with (
        httpx.Client(base_url=OLLAMA_BASE_URL, timeout=120) as client,
        connect_to_database() as connection,
    ):
        retriever = VectorMetricRetriever(
            connection=connection,
            provider=OllamaEmbeddingProvider(
                client=client,
                model=EMBEDDING_MODEL,
            ),
        )
        report = evaluate_metric_queries(retriever, suite, top_k=5)

    write_metric_query_evaluation_report(report, REPORT_PATH)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
