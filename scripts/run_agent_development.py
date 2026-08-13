from __future__ import annotations

import json
from pathlib import Path

from retail_analytics_agent.agent_evaluation import evaluate_cases, load_cases
from retail_analytics_agent.agent_models import ToolResult
from retail_analytics_agent.operations_workflow import OperationsWorkflow
from retail_analytics_agent.tool_registry import ToolRegistry, ToolSpec


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    registry = ToolRegistry()
    for name in ("catalog.retrieve", "sql.query", "knowledge.search", "chart.build", "report.compose", "report.export"):
        evidence = (f"{name}:eval",) if name in {"sql.query", "knowledge.search"} else ()
        registry.register(
            ToolSpec(name=name, description=f"evaluation {name}"),
            lambda payload, context, tool=name, ids=evidence: ToolResult(
                tool_name=tool, status="succeeded", evidence_ids=ids,
            ),
        )
    report = evaluate_cases(
        load_cases(root / "evaluation" / "agent_development.jsonl"),
        OperationsWorkflow(registry),
    )
    output = root / "evaluation" / "reports" / "agent-development-deterministic.json"
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({
        "dataset": report.dataset,
        "cases": len(report.records),
        "skill_route_accuracy": report.skill_route_accuracy,
        "refusal_accuracy": report.refusal_accuracy,
        "tool_allowlist_accuracy": report.tool_allowlist_accuracy,
        "evidence_completeness": report.evidence_completeness,
        "output": str(output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
