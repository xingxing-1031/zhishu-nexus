from pathlib import Path

from retail_analytics_agent.metric_retrieval import KeywordMetricRetriever
from retail_analytics_agent.metric_retrieval_evaluation import (
    evaluate_metric_queries,
    load_metric_query_evaluation_suite,
    write_metric_query_evaluation_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_SUITE_PATH = PROJECT_ROOT / "evaluation" / "metric_query_gold.json"
REPORT_PATH = (
    PROJECT_ROOT / "evaluation" / "reports" / "keyword_metric_baseline.json"
)


def main() -> None:
    suite = load_metric_query_evaluation_suite(GOLD_SUITE_PATH)
    report = evaluate_metric_queries(KeywordMetricRetriever(), suite, top_k=5)
    write_metric_query_evaluation_report(report, REPORT_PATH)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
