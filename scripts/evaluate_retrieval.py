from pathlib import Path

from retail_analytics_agent.retrieval_evaluation import (
    evaluate_retrieval,
    load_retrieval_evaluation_suite,
    write_retrieval_evaluation_report,
)
from retail_analytics_agent.workflow_tools import CatalogRetrievalTool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_SUITE_PATH = PROJECT_ROOT / "evaluation" / "retrieval_gold.json"
REPORT_PATH = PROJECT_ROOT / "evaluation" / "reports" / "catalog_baseline.json"


def main() -> None:
    suite = load_retrieval_evaluation_suite(GOLD_SUITE_PATH)
    report = evaluate_retrieval(CatalogRetrievalTool(), suite)
    write_retrieval_evaluation_report(report, REPORT_PATH)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
