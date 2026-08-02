from pathlib import Path

import httpx

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.distance_threshold import (
    collect_vector_distance_observations,
    select_distance_threshold,
)
from retail_analytics_agent.embeddings import OllamaEmbeddingProvider
from retail_analytics_agent.metric_retrieval_evaluation import (
    load_metric_query_evaluation_suite,
)
from retail_analytics_agent.vector_metric_retrieval import VectorMetricRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_PATH = PROJECT_ROOT / "evaluation" / "metric_query_validation.json"
REPORT_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "reports"
    / "vector_threshold_validation.json"
)


def main() -> None:
    suite = load_metric_query_evaluation_suite(VALIDATION_PATH)
    with (
        httpx.Client(base_url="http://127.0.0.1:11434", timeout=120) as client,
        connect_to_database() as connection,
    ):
        retriever = VectorMetricRetriever(
            connection=connection,
            provider=OllamaEmbeddingProvider(client=client, model="bge-m3"),
            max_distance=None,
        )
        observations = collect_vector_distance_observations(retriever, suite)

    report = select_distance_threshold(suite.suite_id, observations)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
