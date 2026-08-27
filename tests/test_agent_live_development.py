from scripts.run_agent_live_development import (
    _aggregate,
    _evaluate_case,
    _post_json_with_rate_limit_retry,
)


def test_live_evaluation_requires_exact_tools_and_governed_evidence() -> None:
    case = {
        "expected_mode": "collaboration",
        "expected_skill": "refund_diagnosis",
        "expected_statuses": ["succeeded"],
        "expected_tools": ["sql.query", "knowledge.search", "report.export"],
        "requires_data_evidence": True,
        "requires_document_evidence": True,
        "requires_export": True,
    }
    response = {
        "status": "succeeded",
        "agent_mode": "collaboration",
        "skill_id": "refund_diagnosis",
        "tool_calls": [
            {"tool_name": "sql.query", "status": "succeeded"},
            {"tool_name": "report.export", "status": "succeeded"},
            {"tool_name": "knowledge.search", "status": "succeeded"},
        ],
        "context": {"token_estimate": 100, "token_budget": 1000},
        "report": {"data_evidence": ["query:1"], "document_evidence": []},
        "knowledge_evidence": [{"source_id": "ev:1"}],
        "exported_report": "# report",
    }

    checks = _evaluate_case(case, response)

    assert checks["case_pass"] is True
    assert checks["mode_pass"] is True
    assert checks["reason_pass"] is True
    assert checks["document_evidence_count"] == 1


def test_live_evaluation_checks_expected_reason_code_in_limitations() -> None:
    case = {
        "expected_mode": "general",
        "expected_skill": None,
        "expected_statuses": ["refused"],
        "expected_tools": [],
        "expected_reason_code": "write_operation_refused",
        "requires_data_evidence": False,
        "requires_document_evidence": False,
        "requires_export": False,
    }
    matched = {
        "status": "refused",
        "agent_mode": "general",
        "skill_id": None,
        "tool_calls": [],
        "limitations": ["write_operation_refused"],
        "context": {"token_estimate": None, "token_budget": None},
        "report": {},
    }
    mismatched = dict(matched, limitations=["role_elevation_refused"])

    assert _evaluate_case(case, matched)["reason_pass"] is True
    assert _evaluate_case(case, matched)["case_pass"] is True
    assert _evaluate_case(case, mismatched)["reason_pass"] is False
    assert _evaluate_case(case, mismatched)["case_pass"] is False


def test_live_evaluation_rejects_context_over_budget() -> None:
    case = {
        "expected_skill": "channel_comparison",
        "expected_statuses": ["succeeded"],
        "expected_tools": ["sql.query", "knowledge.search"],
        "requires_data_evidence": True,
        "requires_document_evidence": False,
        "requires_export": False,
    }
    response = {
        "status": "succeeded",
        "skill_id": "channel_comparison",
        "tool_calls": [
            {"tool_name": "sql.query", "status": "succeeded"},
            {"tool_name": "knowledge.search", "status": "succeeded"},
        ],
        "context": {"token_estimate": 1001, "token_budget": 1000},
        "report": {"data_evidence": ["query:1"]},
    }

    checks = _evaluate_case(case, response)

    assert checks["context_budget_pass"] is False
    assert checks["case_pass"] is False


def test_live_aggregate_keeps_success_degradation_and_refusal_separate() -> None:
    records = [
        {
            "expected_skill": "refund_diagnosis",
            "expected_statuses": ["succeeded", "degraded"],
            "status": "degraded",
            "http_status": 200,
            "rate_limit_retry_count": 0,
            "rate_limit_wait_seconds": 0.0,
            "latency_seconds": 2.0,
            "tool_calls": [{"tool_name": "sql.query", "status": "succeeded"}],
            "checks": {
                "case_pass": True,
                "route_pass": True,
                "tool_pass": True,
                "data_evidence_pass": True,
                "document_evidence_pass": True,
                "context_budget_pass": True,
                "token_estimate": 100,
                "token_budget": 1000,
            },
        },
        {
            "expected_skill": None,
            "expected_statuses": ["refused"],
            "status": "refused",
            "http_status": 200,
            "rate_limit_retry_count": 0,
            "rate_limit_wait_seconds": 0.0,
            "latency_seconds": 1.0,
            "tool_calls": [],
            "checks": {
                "case_pass": True,
                "route_pass": True,
                "tool_pass": True,
                "data_evidence_pass": True,
                "document_evidence_pass": True,
                "context_budget_pass": True,
                "token_estimate": None,
                "token_budget": None,
            },
        },
    ]

    metrics = _aggregate(records)

    assert metrics["case_pass_rate"] == 1.0
    assert metrics["business_succeeded_rate"] == 0.0
    assert metrics["business_non_failure_rate"] == 1.0
    assert metrics["refusal_accuracy"] == 1.0
    assert metrics["context_budget_compliance"] == 1.0


def test_live_aggregate_excludes_expected_skill_refusal_from_business_rate() -> None:
    records = [
        {
            "expected_skill": "product_analysis",
            "expected_statuses": ["refused"],
            "status": "refused",
            "http_status": 200,
            "rate_limit_retry_count": 0,
            "rate_limit_wait_seconds": 0.0,
            "latency_seconds": 1.0,
            "tool_calls": [{"tool_name": "sql.query", "status": "succeeded"}],
            "checks": {
                "case_pass": True,
                "route_pass": True,
                "tool_pass": True,
                "data_evidence_pass": True,
                "document_evidence_pass": True,
                "context_budget_pass": True,
                "token_estimate": 10,
                "token_budget": 1000,
            },
        },
        {
            "expected_skill": "product_analysis",
            "expected_statuses": ["succeeded"],
            "status": "succeeded",
            "http_status": 200,
            "rate_limit_retry_count": 0,
            "rate_limit_wait_seconds": 0.0,
            "latency_seconds": 2.0,
            "tool_calls": [{"tool_name": "sql.query", "status": "succeeded"}],
            "checks": {
                "case_pass": True,
                "route_pass": True,
                "tool_pass": True,
                "data_evidence_pass": True,
                "document_evidence_pass": True,
                "context_budget_pass": True,
                "token_estimate": 100,
                "token_budget": 1000,
            },
        },
    ]

    metrics = _aggregate(records)

    assert metrics["business_succeeded_rate"] == 1.0
    assert metrics["business_non_failure_rate"] == 1.0


def test_live_request_waits_for_retry_after_on_rate_limit() -> None:
    responses = iter(
        [
            (429, {"detail": "too many requests"}, 3.0),
            (200, {"status": "refused"}, None),
        ]
    )
    waits: list[float] = []

    status, payload, retry_count, wait_seconds = _post_json_with_rate_limit_retry(
        post_json=lambda: next(responses),
        max_retries=2,
        wait=waits.append,
    )

    assert status == 200
    assert payload == {"status": "refused"}
    assert retry_count == 1
    assert wait_seconds == 3.0
    assert waits == [3.0]


def test_live_aggregate_reports_metrics_by_agent_category() -> None:
    records = [
        {
            "category": "general",
            "expected_statuses": ["succeeded"],
            "status": "succeeded",
            "http_status": 200,
            "rate_limit_retry_count": 0,
            "rate_limit_wait_seconds": 0.0,
            "latency_seconds": 1.5,
            "tool_calls": [],
            "checks": {
                "case_pass": True,
                "mode_pass": True,
                "route_pass": True,
                "tool_pass": True,
                "data_evidence_pass": True,
                "document_evidence_pass": True,
                "context_budget_pass": True,
                "token_estimate": 100,
                "token_budget": 1000,
            },
        }
    ]

    metrics = _aggregate(records)

    assert metrics["agent_mode_accuracy"] == 1.0
    assert metrics["by_category"]["general"]["case_count"] == 1
    assert metrics["by_category"]["general"]["agent_mode_accuracy"] == 1.0
