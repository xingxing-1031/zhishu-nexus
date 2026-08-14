from argparse import ArgumentParser
from pathlib import Path

import httpx

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.embeddings import OllamaEmbeddingProvider
from retail_analytics_agent.hybrid_metric_retrieval import HybridMetricRetriever
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
GOLD_SUITE_PATH = PROJECT_ROOT / "evaluation" / "metric_query_gold.json"
def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--model", default="qwen3:4b")
    args = parser.parse_args()
    report_name = "llm_reranker_" + args.model.replace(":", "_").replace(".", "_")
    report_path = (
        PROJECT_ROOT / "evaluation" / "reports" / f"{report_name}.json"
    )
    suite = load_metric_query_evaluation_suite(GOLD_SUITE_PATH)
    with (
        httpx.Client(base_url="http://127.0.0.1:11434", timeout=120) as client,
        connect_to_database() as connection,
    ):
        candidate_retriever = HybridMetricRetriever(
            keyword_retriever=KeywordMetricRetriever(),
            vector_retriever=VectorMetricRetriever(
                connection=connection,
                provider=OllamaEmbeddingProvider(client=client, model="bge-m3"),
                max_distance=None,
            ),
        )
        retriever = RerankedMetricRetriever(
            candidate_retriever=candidate_retriever,
            reranker=OllamaLLMMetricReranker(
                client=client,
                model=args.model,
            ),
        )
        report = evaluate_metric_queries(retriever, suite, top_k=5)

    write_metric_query_evaluation_report(report, report_path)
    print(f"Reranker model: {args.model}")
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
