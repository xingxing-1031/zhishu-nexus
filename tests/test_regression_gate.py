from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from retail_analytics_agent.access_control import AccessPolicy, authorize
from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.checkpoint_meta import (
    CheckpointMeta,
    InMemoryCheckpointMetaStore,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
)
from retail_analytics_agent.tracing import TraceErrorCategory, classify_error_type
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalToolError,
    SQLBusinessConsistencyToolError,
    SQLExecutionToolError,
    SQLValidationToolError,
)

_GATE_REQUEST_ID = "REQ-GATE-001"
_FAULT_CASES_PATH = (
    Path(__file__).parent.parent / "evaluation" / "fault_cases.jsonl"
)


def _load_fault_cases() -> tuple[dict, ...]:
    with _FAULT_CASES_PATH.open(encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle if line.strip())


def _fault_exception(fault: dict) -> Exception:
    name = fault["fault"]
    if name == "model_timeout":
        return httpx.TimeoutException("model timed out")
    if name == "model_invalid_json":
        return ValueError("model returned invalid json")
    if name in ("tool_timeout", "tool_unauthorized", "database_unavailable"):
        return SQLExecutionToolError(name)
    if name == "rag_empty_evidence":
        return CatalogRetrievalToolError("no evidence found")
    if name == "sql_ast_rejected":
        return SQLValidationToolError("SQL AST rejected")
    if name == "business_check_failed":
        return SQLBusinessConsistencyToolError("business check failed")
    if name == "checkpoint_corrupted":
        return RuntimeError("checkpoint state version mismatch")
    if name == "approval_resume_duplicate":
        return ValueError("approval request is not pending")
    if name == "sse_disconnect":
        return RuntimeError("sse reconnect")
    raise AssertionError(f"unknown fault: {name}")


# --- 回归门禁：fault_cases.jsonl 变为门禁数据源（Tool 归因合约） ---------


def test_gate_fault_cases_jsonl_attribution() -> None:
    cases = _load_fault_cases()
    assert len(cases) == 11, "fault_cases.jsonl must keep the fixed fault set"
    for fault in cases:
        exc = _fault_exception(fault)
        category = classify_error_type(type(exc).__name__, str(exc))
        assert category is not None, fault["fault"]
        assert category.value == fault["expected_category"], fault["fault"]


def test_gate_core_success_rate_floor() -> None:
    cases = _load_fault_cases()
    correct = sum(
        1
        for fault in cases
        if classify_error_type(
            type(_fault_exception(fault)).__name__, str(_fault_exception(fault))
        ).value
        == fault["expected_category"]
    )
    assert correct / len(cases) >= 0.9, (
        "关键链路归因成功率不能低于上一基线"
    )


# --- 回归门禁：冻结集能力（不因后续改动倒退） ---------------------------


def test_gate_frozen_no_permission_leak() -> None:
    analyst = AccessContext(user_id="USER-001", role=AccessRole.ANALYST)
    decision = authorize(
        analyst,
        "dataset.select",
        "dataset:ds-b",
        policy=AccessPolicy(authorized_datasets=frozenset({"ds-a"})),
    )
    assert not decision.allowed
    assert decision.reason == "dataset not authorized"
    assert classify_error_type("PermissionError", decision.reason) is (
        TraceErrorCategory.PERMISSION
    )


def test_gate_checkpoint_recovery_pass() -> None:
    graph = Mock()
    meta = InMemoryCheckpointMetaStore()
    meta.save(
        CheckpointMeta(
            request_id=_GATE_REQUEST_ID,
            user_id="USER-001",
            state_version=0,
        )
    )

    with pytest.raises(
        RuntimeError,
        match="checkpoint state version mismatch",
    ):
        LangGraphAnalysisRunner(graph, checkpoint_meta=meta).run(
            AnalysisRequest(
                request_id=_GATE_REQUEST_ID,
                user_id="USER-001",
                question="各渠道销售额",
                max_rows=10,
            ),
            AccessContext(user_id="USER-001", role=AccessRole.ANALYST),
        )

    graph.invoke.assert_not_called()
