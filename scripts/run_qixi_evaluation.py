from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from retail_analytics_agent.agent_models import AgentResponse
from retail_analytics_agent.qixi_evaluation import (
    QixiEvaluationCase,
    evaluate_qixi_cases,
    load_qixi_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", default="evaluation/qixi_development.jsonl")
    parser.add_argument("--output-dir", default="evaluation/reports")
    args = parser.parse_args()
    dataset_path = Path(args.dataset)
    cases = load_qixi_cases(dataset_path.read_text(encoding="utf-8").splitlines())
    client = httpx.Client(base_url=args.base_url, timeout=180)
    session = client.get("/session")
    session.raise_for_status()
    user_id = session.json()["user_id"]

    def execute(case: QixiEvaluationCase) -> AgentResponse:
        response = client.post(
            "/agent/run",
            json={
                "request_id": f"QIXI-EVAL-{case.case_id}",
                "conversation_id": f"qixi-eval-{case.case_id}",
                "user_id": user_id,
                "question": case.question,
                "max_rows": 20,
            },
        )
        response.raise_for_status()
        return AgentResponse.model_validate(response.json())

    try:
        report = evaluate_qixi_cases(cases, execute, dataset=dataset_path.name)
    finally:
        client.close()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"qixi-development-{timestamp}.json"
    output.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
