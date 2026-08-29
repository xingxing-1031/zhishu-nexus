from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
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
) -> tuple[int, dict[str, Any], float | None]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=True).encode("ascii"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return (
                response.status,
                json.loads(response.read().decode("utf-8")),
                None,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body}
        retry_after = exc.headers.get("Retry-After")
        try:
            retry_after_seconds = float(retry_after) if retry_after else None
        except ValueError:
            retry_after_seconds = None
        return exc.code, parsed, retry_after_seconds


def _post_json_with_rate_limit_retry(
    *,
    post_json: Callable[[], tuple[int, dict[str, Any], float | None]],
    max_retries: int,
    wait: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, Any], int, float]:
    retry_count = 0
    wait_seconds = 0.0
    while True:
        status, payload, retry_after = post_json()
        if status != 429 or retry_count >= max_retries:
            return status, payload, retry_count, wait_seconds
        delay = max(1.0, retry_after or 1.0)
        wait(delay)
        retry_count += 1
        wait_seconds += delay


def _evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    report = response.get("report") or {}
    context = response.get("context") or {}
    tool_calls = response.get("tool_calls") or []
    actual_tools = [item.get("tool_name") for item in tool_calls]
    expected_tools = case["expected_tools"]
    expected_mode = case.get("expected_mode")
    status_pass = response.get("status") in case["expected_statuses"]
    mode_pass = expected_mode is None or response.get("agent_mode") == expected_mode
    route_pass = response.get("skill_id") == case["expected_skill"]
    tool_pass = Counter(actual_tools) == Counter(expected_tools)
    data_pass = (
        not case["requires_data_evidence"]
        or bool(report.get("data_evidence"))
    )
    document_pass = (
        not case["requires_document_evidence"]
        or bool(report.get("document_evidence"))
        or bool(response.get("knowledge_evidence"))
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
    expected_reason_code = case.get("expected_reason_code")
    limitations = [str(item) for item in (response.get("limitations") or [])]
    reason_pass = expected_reason_code is None or expected_reason_code in limitations
    return {
        "status_pass": status_pass,
        "mode_pass": mode_pass,
        "route_pass": route_pass,
        "tool_pass": tool_pass,
        "data_evidence_pass": data_pass,
        "document_evidence_pass": document_pass,
        "export_pass": export_pass,
        "tools_succeeded": tools_succeeded,
        "context_budget_pass": context_budget_pass,
        "reason_pass": reason_pass,
        "case_pass": all(
            (
                status_pass,
                mode_pass,
                route_pass,
                tool_pass,
                data_pass,
                document_pass,
                export_pass,
                tools_succeeded,
                context_budget_pass,
                reason_pass,
            )
        ),
        "actual_tools": actual_tools,
        "actual_mode": response.get("agent_mode"),
        "data_evidence_count": len(report.get("data_evidence") or []),
        "document_evidence_count": max(
            len(report.get("document_evidence") or []),
            len(response.get("knowledge_evidence") or []),
        ),
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
    metrics = {
        "case_count": total,
        "case_pass_rate": rate(lambda record: record["checks"]["case_pass"]),
        "agent_mode_accuracy": rate(
            lambda record: record["checks"].get("mode_pass", True)
        ),
        "skill_route_accuracy": rate(lambda record: record["checks"]["route_pass"]),
        "tool_selection_accuracy": rate(lambda record: record["checks"]["tool_pass"]),
        "evidence_requirement_accuracy": rate(
            lambda record: record["checks"]["data_evidence_pass"]
            and record["checks"]["document_evidence_pass"]
        ),
        "context_budget_compliance": rate(
            lambda record: record["checks"]["context_budget_pass"]
        ),
        "business_succeeded_rate": (
            round(
                sum(record["status"] == "succeeded" for record in executable)
                / len(executable),
                4,
            )
            if executable
            else None
        ),
        "business_non_failure_rate": (
            round(
                sum(
                    record["status"] in {"succeeded", "degraded"}
                    for record in executable
                )
                / len(executable),
                4,
            )
            if executable
            else None
        ),
        "refusal_accuracy": (
            round(
                sum(record["status"] == "refused" for record in refusals)
                / len(refusals),
                4,
            )
            if refusals
            else None
        ),
        "http_success_rate": rate(lambda record: record["http_status"] == 200),
        "rate_limit_retry_count": sum(
            record["rate_limit_retry_count"] for record in records
        ),
        "rate_limit_wait_seconds": round(
            sum(record["rate_limit_wait_seconds"] for record in records),
            3,
        ),
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
    metrics["by_category"] = _aggregate_by_category(records)
    return metrics


def _aggregate_by_category(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.get("category", "uncategorized"), []).append(record)

    result: dict[str, dict[str, Any]] = {}
    for category, items in sorted(grouped.items()):
        total = len(items)
        executable = [item for item in items if "refused" not in item["expected_statuses"]]
        refusals = [item for item in items if item["expected_statuses"] == ["refused"]]
        latencies = [item["latency_seconds"] for item in items]

        def rate(predicate) -> float:
            return round(sum(1 for item in items if predicate(item)) / total, 4)

        result[category] = {
            "case_count": total,
            "case_pass_rate": rate(lambda item: item["checks"]["case_pass"]),
            "agent_mode_accuracy": rate(
                lambda item: item["checks"].get("mode_pass", True)
            ),
            "skill_route_accuracy": rate(lambda item: item["checks"]["route_pass"]),
            "tool_selection_accuracy": rate(lambda item: item["checks"]["tool_pass"]),
            "evidence_requirement_accuracy": rate(
                lambda item: item["checks"]["data_evidence_pass"]
                and item["checks"]["document_evidence_pass"]
            ),
            "context_budget_compliance": rate(
                lambda item: item["checks"]["context_budget_pass"]
            ),
            "business_succeeded_rate": (
                round(sum(item["status"] == "succeeded" for item in executable) / len(executable), 4)
                if executable
                else None
            ),
            "business_non_failure_rate": (
                round(
                    sum(item["status"] in {"succeeded", "degraded"} for item in executable)
                    / len(executable),
                    4,
                )
                if executable
                else None
            ),
            "refusal_accuracy": (
                round(sum(item["status"] == "refused" for item in refusals) / len(refusals), 4)
                if refusals
                else None
            ),
            "latency_seconds": {
                "p50": round(_percentile(latencies, 0.50), 3),
                "p95": round(_percentile(latencies, 0.95), 3),
                "max": round(max(latencies), 3),
            },
        }
    return result


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
    parser.add_argument(
        "--executor",
        choices=("live_agent", "runtime_probe", "all"),
        default="live_agent",
        help="Select cases by evaluation_executor; runtime probes use their dedicated runner.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=240)
    parser.add_argument("--interval-seconds", type=float, default=2)
    parser.add_argument("--rate-limit-retries", type=int, default=2)
    parser.add_argument("--token-budget", type=int, default=1600)
    parser.add_argument(
        "--runtime-commit",
        help="Deployed commit SHA; defaults to the current local HEAD.",
    )
    parser.add_argument(
        "--data-snapshot-id",
        default="demo-live-seed@HEAD (db/seeds/001+002, 910 orders / 180d)",
        help="Data snapshot identifier recorded in the report annotations.",
    )
    parser.add_argument(
        "--reference-time",
        default="unfixed (demo seed relative time, evaluated per request)",
        help="Reference time policy recorded in the report annotations.",
    )
    parser.add_argument(
        "--model-name",
        default="qwen-plus (dashscope compatible-mode)",
        help="Runtime model version recorded in the report annotations.",
    )
    args = parser.parse_args()
    cases = _load_cases(args.cases)
    if args.executor != "all":
        cases = [
            case for case in cases
            if case.get("evaluation_executor", "live_agent") == args.executor
        ]
    if not cases:
        raise SystemExit(f"no cases for executor={args.executor}")
    password = os.getenv(args.password_env)
    if not password:
        raise SystemExit(f"missing environment variable: {args.password_env}")

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    status, _session, _retry_after = _post_json(
        opener,
        f"{args.base_url.rstrip('/')}/auth/login",
        {"username": args.username, "password": password},
        args.timeout_seconds,
    )
    if status != 200:
        raise SystemExit(f"login failed with HTTP {status}")

    records: list[dict[str, Any]] = []
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for index, case in enumerate(cases):
        request_id = f"agent-live-{run_id}-{index + 1:02d}-{uuid4().hex[:6]}"
        started = time.perf_counter()
        try:
            (
                http_status,
                response,
                rate_limit_retry_count,
                rate_limit_wait_seconds,
            ) = _post_json_with_rate_limit_retry(
                post_json=lambda: _post_json(
                    opener,
                    f"{args.base_url.rstrip('/')}/agent/run",
                    {
                        "request_id": request_id,
                        "conversation_id": (
                            f"agent-live-{run_id}-{index + 1:02d}"
                        ),
                        "user_id": "ANALYST-001",
                        "question": case["question"],
                        "max_rows": 20,
                        "token_budget": args.token_budget,
                    },
                    args.timeout_seconds,
                ),
                max_retries=args.rate_limit_retries,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Remote transport failure keeps the case in the denominator
            # instead of aborting the whole run.
            http_status = 0
            response = {"status": None, "limitations": [f"transport_error: {exc}"]}
            rate_limit_retry_count = 0
            rate_limit_wait_seconds = 0.0
        latency = time.perf_counter() - started
        checks = _evaluate_case(case, response)
        records.append(
            {
                **case,
                "request_id": request_id,
                "http_status": http_status,
                "rate_limit_retry_count": rate_limit_retry_count,
                "rate_limit_wait_seconds": rate_limit_wait_seconds,
                "latency_seconds": round(latency, 3),
                "status": response.get("status"),
                "agent_mode": response.get("agent_mode"),
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

        # Persist intermediate state after every case so a crashed or killed
        # run still leaves a usable partial report behind.
        output = root / "evaluation" / "reports" / f"agent-live-development-{run_id}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
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
                    "annotations": {
                        "data_snapshot_id": args.data_snapshot_id,
                        "reference_time": args.reference_time,
                        "model_name": args.model_name,
                        "evaluation_date": datetime.now(UTC).isoformat(),
                    },
                    "partial": index + 1 < len(cases),
                    "metrics": _aggregate(records),
                    "records": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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
        "annotations": {
            "data_snapshot_id": args.data_snapshot_id,
            "reference_time": args.reference_time,
            "model_name": args.model_name,
            "evaluation_date": datetime.now(UTC).isoformat(),
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
