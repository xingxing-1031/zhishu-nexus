from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from uuid import uuid4


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(percentile * len(ordered) + 0.999) - 1))
    return ordered[index]


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=True).encode("ascii"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body}
        return exc.code, parsed


def _evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    report = response.get("report") or {}
    context = response.get("context") or {}
    tool_calls = response.get("tool_calls") or []
    actual_tools = [item.get("tool_name") for item in tool_calls]
    expected_tools = case["expected_tools"]
    status_pass = response.get("status") in case["expected_statuses"]
    route_pass = response.get("skill_id") == case["expected_skill"]
    tool_pass = actual_tools == expected_tools
    data_pass = (
        not case["requires_data_evidence"]
        or bool(report.get("data_evidence"))
    )
    document_pass = (
        not case["requires_document_evidence"]
        or bool(report.get("document_evidence"))
    )
    export_pass = not case["requires_export"] or bool(
        response.get("exported_report")
    )
    tools_succeeded = all(item.get("status") == "succeeded" for item in tool_calls)
    token_estimate = context.get("token_estimate")
    token_budget = context.get("token_budget")
    context_budget_pass = (
        token_estimate is None
        or token_budget is None
        or token_estimate <= token_budget
    )
    return {
        "status_pass": status_pass,
        "route_pass": route_pass,
        "tool_pass": tool_pass,
        "data_evidence_pass": data_pass,
        "document_evidence_pass": document_pass,
        "export_pass": export_pass,
        "tools_succeeded": tools_succeeded,
        "context_budget_pass": context_budget_pass,
        "case_pass": all(
            (
                status_pass,
                route_pass,
                tool_pass,
                data_pass,
                document_pass,
                export_pass,
                tools_succeeded,
                context_budget_pass,
            )
        ),
        "actual_tools": actual_tools,
        "data_evidence_count": len(report.get("data_evidence") or []),
        "document_evidence_count": len(report.get("document_evidence") or []),
        "token_estimate": token_estimate,
        "token_budget": token_budget,
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    latencies = [record["latency_seconds"] for record in records]
    executable = [
        record
        for record in records
        if "refused" not in record["expected_statuses"]
    ]
    refusals = [
        record
        for record in records
        if record["expected_statuses"] == ["refused"]
    ]
    token_ratios = [
        record["checks"]["token_estimate"] / record["checks"]["token_budget"]
        for record in records
        if record["checks"]["token_estimate"] is not None
        and record["checks"]["token_budget"]
    ]

    def rate(predicate) -> float:
        return round(sum(1 for record in records if predicate(record)) / total, 4)

    tool_calls = [item for record in records for item in record["tool_calls"]]
    tool_success: dict[str, float] = {}
    for name in sorted({item["tool_name"] for item in tool_calls}):
        selected = [item for item in tool_calls if item["tool_name"] == name]
        tool_success[name] = round(
            sum(item["status"] == "succeeded" for item in selected) / len(selected),
            4,
        )
    return {
        "case_count": total,
        "case_pass_rate": rate(lambda record: record["checks"]["case_pass"]),
        "skill_route_accuracy": rate(lambda record: record["checks"]["route_pass"]),
        "tool_selection_accuracy": rate(lambda record: record["checks"]["tool_pass"]),
        "evidence_requirement_accuracy": rate(
            lambda record: record["checks"]["data_evidence_pass"]
            and record["checks"]["document_evidence_pass"]
        ),
        "context_budget_compliance": rate(
            lambda record: record["checks"]["context_budget_pass"]
        ),
        "business_succeeded_rate": round(
            sum(record["status"] == "succeeded" for record in executable)
            / len(executable),
            4,
        ),
        "business_non_failure_rate": round(
            sum(record["status"] in {"succeeded", "degraded"} for record in executable)
            / len(executable),
            4,
        ),
        "refusal_accuracy": round(
            sum(record["status"] == "refused" for record in refusals)
            / len(refusals),
            4,
        ),
        "http_success_rate": rate(lambda record: record["http_status"] == 200),
        "tool_success_rate_by_name": tool_success,
        "latency_seconds": {
            "mean": round(statistics.fmean(latencies), 3),
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "max": round(max(latencies), 3),
        },
        "context_budget_usage": {
            "mean": round(statistics.fmean(token_ratios), 4) if token_ratios else None,
            "max": round(max(token_ratios), 4) if token_ratios else None,
        },
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://106.52.176.63")
    parser.add_argument("--username", default="analyst-demo")
    parser.add_argument("--password-env", default="AGENT_DEMO_PASSWORD")
    parser.add_argument(
        "--cases",
        type=Path,
        default=root / "evaluation" / "agent_live_development.jsonl",
    )
    parser.add_argument("--timeout-seconds", type=float, default=240)
    parser.add_argument("--interval-seconds", type=float, default=2)
    parser.add_argument("--token-budget", type=int, default=1600)
    parser.add_argument(
        "--runtime-commit",
        help="Deployed commit SHA; defaults to the current local HEAD.",
    )
    args = parser.parse_args()
    password = os.getenv(args.password_env)
    if not password:
        raise SystemExit(f"missing environment variable: {args.password_env}")

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    status, _session = _post_json(
        opener,
        f"{args.base_url.rstrip('/')}/auth/login",
        {"username": args.username, "password": password},
        args.timeout_seconds,
    )
    if status != 200:
        raise SystemExit(f"login failed with HTTP {status}")

    records: list[dict[str, Any]] = []
    cases = _load_cases(args.cases)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for index, case in enumerate(cases):
        request_id = f"agent-live-{run_id}-{index + 1:02d}-{uuid4().hex[:6]}"
        started = time.perf_counter()
        http_status, response = _post_json(
            opener,
            f"{args.base_url.rstrip('/')}/agent/run",
            {
                "request_id": request_id,
                "conversation_id": f"agent-live-{run_id}-{index + 1:02d}",
                "user_id": "ANALYST-001",
                "question": case["question"],
                "max_rows": 20,
                "token_budget": args.token_budget,
            },
            args.timeout_seconds,
        )
        latency = time.perf_counter() - started
        checks = _evaluate_case(case, response)
        records.append(
            {
                **case,
                "request_id": request_id,
                "http_status": http_status,
                "latency_seconds": round(latency, 3),
                "status": response.get("status"),
                "skill_id": response.get("skill_id"),
                "tool_calls": response.get("tool_calls") or [],
                "limitations": response.get("limitations") or [],
                "analysis_status": (response.get("analysis") or {}).get("status"),
                "analysis_answer": (response.get("analysis") or {}).get("answer"),
                "checks": checks,
            }
        )
        print(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "status": response.get("status"),
                    "latency_seconds": round(latency, 3),
                    "case_pass": checks["case_pass"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if index + 1 < len(cases):
            time.sleep(args.interval_seconds)

    report = {
        "dataset": args.cases.name,
        "dataset_kind": "live_development",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "runtime_commit": args.runtime_commit or _git_commit(root),
        "conditions": {
            "public_vps": True,
            "remote_model": True,
            "postgresql": True,
            "enterprise_rag": True,
            "mcp_export": True,
            "token_budget": args.token_budget,
        },
        "metrics": _aggregate(records),
        "records": records,
    }
    output = root / "evaluation" / "reports" / f"agent-live-development-{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    latest = root / "evaluation" / "reports" / "agent-live-development-latest.json"
    latest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"metrics": report["metrics"], "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
