"""Quality gates for the final Agent evaluation datasets."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_CATEGORIES = {"general", "knowledge", "data", "collaboration", "safety"}
ALLOWED_TOOLS = {"time.now", "weather.current", "exchange.rate", "web.search", "knowledge.search", "sql.query", "report.export"}
ALLOWED_TRACKS = {"business", "runtime_budget", "runtime_recovery", "runtime_injection", "runtime_default_deny", "runtime_isolation"}
ALLOWED_SKILLS = {None, "channel_comparison", "product_analysis", "refund_diagnosis", "weekly_report"}
ALLOWED_EXECUTORS = {"live_agent", "runtime_probe"}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(dev: list[dict], holdout: list[dict]) -> None:
    assert len(dev) == 100, len(dev)
    assert len(holdout) == 30, len(holdout)
    assert len({x["case_id"] for x in dev}) == 100
    assert len({x["case_id"] for x in holdout}) == 30
    assert not ({x["case_id"] for x in dev} & {x["case_id"] for x in holdout})
    assert not ({x["question"] for x in dev} & {x["question"] for x in holdout})
    assert Counter(x["category"] for x in dev) == Counter({"safety": 38, "data": 20, "knowledge": 15, "collaboration": 15, "general": 12})
    assert sum(x.get("evaluation_track") == "runtime_budget" for x in dev) == 6
    assert sum(x.get("evaluation_track") == "runtime_recovery" for x in dev) == 5
    assert sum(x.get("evaluation_track") == "runtime_injection" for x in dev) == 8
    assert sum(x.get("evaluation_track") == "runtime_default_deny" for x in dev) == 5
    assert sum(x.get("evaluation_track") == "runtime_isolation" for x in dev) == 6
    assert sum(x.get("evaluation_track") != "business" for x in holdout) >= 8
    required = {"case_id", "category", "question", "expected_mode", "expected_skill", "expected_statuses", "expected_tools", "requires_data_evidence", "requires_document_evidence", "requires_export", "evaluation_track", "evaluation_executor"}
    for case in dev + holdout:
        assert required <= case.keys(), case["case_id"]
        assert case["category"] in ALLOWED_CATEGORIES
        assert case["evaluation_track"] in ALLOWED_TRACKS
        assert case["expected_skill"] in ALLOWED_SKILLS, case["case_id"]
        assert case["expected_statuses"]
        assert set(case["expected_tools"]) <= ALLOWED_TOOLS, case["case_id"]
        assert case["evaluation_executor"] in ALLOWED_EXECUTORS, case["case_id"]
        if case["category"] == "safety":
            assert any(status in {"refused", "degraded", "budget_exceeded"} for status in case["expected_statuses"]), case["case_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate final Agent evaluation datasets")
    parser.add_argument("--development", default=str(ROOT / "evaluation" / "final" / "agent-live-development-final-v4.jsonl"))
    parser.add_argument("--holdout", default=str(ROOT / "evaluation" / "final" / "agent-live-holdout-final-v4.jsonl"))
    args = parser.parse_args()
    dev = load(Path(args.development))
    holdout = load(Path(args.holdout))
    validate(dev, holdout)
    print("final Agent datasets: 100 development + 30 holdout; quality gates passed")
    return 0


if __name__ == "__main__":
    import argparse
    raise SystemExit(main())
