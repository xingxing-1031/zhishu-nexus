from pathlib import Path

from retail_analytics_agent.agent_evaluation import evaluate_cases, load_cases
from retail_analytics_agent.agent_models import ToolResult
from retail_analytics_agent.operations_workflow import OperationsWorkflow
from retail_analytics_agent.tool_registry import ToolRegistry, ToolSpec


def _workflow() -> OperationsWorkflow:
    registry = ToolRegistry()
    for name in ("catalog.retrieve", "sql.query", "knowledge.search", "chart.build", "report.compose", "report.export"):
        ids = (f"{name}:eval",) if name in {"sql.query", "knowledge.search"} else ()
        registry.register(ToolSpec(name=name, description=name), lambda p, c, n=name, i=ids: ToolResult(tool_name=n, status="succeeded", evidence_ids=i))
    return OperationsWorkflow(registry)


def test_agent_development_report_has_sample_level_records() -> None:
    root = Path(__file__).parents[1]
    report = evaluate_cases(load_cases(root / "evaluation" / "agent_development.jsonl"), _workflow())
    assert len(report.records) == 5
    assert report.skill_route_accuracy >= 0.8
    assert all(record.planned_tools or record.status == "refused" for record in report.records)
