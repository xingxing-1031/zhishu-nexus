from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.checkpoint_meta import (
    CheckpointMeta,
    InMemoryCheckpointMetaStore,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisResultStatus,
    ApprovalResolutionRequest,
    ApprovalStatus,
    ChartSpec,
    RetrievalEvidence,
)
from retail_analytics_agent.request_registry import (
    RequestClaim,
    RequestClaimStatus,
    RequestRunStatus,
)
from retail_analytics_agent.sql_safety import prepare_safe_sql
from retail_analytics_agent.workflow import create_initial_state

_REQUEST_ID = "REQ-STATE-001"


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id=_REQUEST_ID,
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )


def _access_context() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _admin_context() -> AccessContext:
    return AccessContext(user_id="ADMIN-001", role=AccessRole.ADMIN)


def _successful_state() -> dict:
    state = create_initial_state(_request())
    state.update(
        {
            "plan": AnalysisPlan(
                analysis_goal="各渠道销售额",
                metrics=["sales_amount"],
                dimensions=["channel"],
            ),
            "sql_valid": True,
            "query_rows": [{"channel": "京东", "sales_amount": "11300.00"}],
            "final_answer": "京东渠道销售额为 11300.00 元。",
            "chart_spec": ChartSpec(
                chart_type="bar",
                title="各渠道销售额",
                x_field="channel",
                y_fields=("sales_amount",),
            ),
            "trace": [
                "plan",
                "retrieve",
                "generate_sql",
                "validate_sql",
                "execute_sql",
                "summarize",
            ],
        }
    )
    return state


def _pending_state() -> dict:
    state = create_initial_state(_request())
    state.update(
        {
            "approval_status": ApprovalStatus.PENDING,
            "trace": ["plan", "validate_sql", "assess_risk"],
        }
    )
    return state


def _claim(
    status: RequestClaimStatus,
    run_status: RequestRunStatus,
) -> RequestClaim:
    return RequestClaim(
        status=status,
        run_status=run_status,
        user_id="USER-001",
        access_role=AccessRole.ANALYST,
    )


# --- 元数据落盘 -------------------------------------------------------


def test_run_tracks_checkpoint_version_and_last_node() -> None:
    graph = Mock()
    graph.invoke.return_value = _successful_state()
    meta = InMemoryCheckpointMetaStore()

    LangGraphAnalysisRunner(graph, checkpoint_meta=meta).run(
        _request(),
        _access_context(),
    )

    entry = meta.get(_REQUEST_ID)
    assert entry is not None
    assert entry.state_version == 1
    assert entry.last_completed_node == "summarize"
    assert entry.user_id == "USER-001"


# --- 恢复校验：过期 / 错误用户 / 旧版本 --------------------------------


def test_expired_checkpoint_is_rejected() -> None:
    graph = Mock()
    meta = InMemoryCheckpointMetaStore()
    meta.save(
        CheckpointMeta(
            request_id=_REQUEST_ID,
            user_id="USER-001",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )

    with pytest.raises(RuntimeError, match="checkpoint has expired"):
        LangGraphAnalysisRunner(graph, checkpoint_meta=meta).run(
            _request(),
            _access_context(),
        )

    graph.invoke.assert_not_called()


def test_checkpoint_for_wrong_user_is_rejected() -> None:
    graph = Mock()
    meta = InMemoryCheckpointMetaStore()
    meta.save(CheckpointMeta(request_id=_REQUEST_ID, user_id="OTHER-USER"))

    with pytest.raises(
        PermissionError,
        match="checkpoint belongs to another user",
    ):
        LangGraphAnalysisRunner(graph, checkpoint_meta=meta).run(
            _request(),
            _access_context(),
        )

    graph.invoke.assert_not_called()


def test_old_state_version_is_rejected() -> None:
    graph = Mock()
    meta = InMemoryCheckpointMetaStore()
    meta.save(
        CheckpointMeta(request_id=_REQUEST_ID, user_id="USER-001", state_version=0)
    )

    with pytest.raises(
        RuntimeError,
        match="checkpoint state version mismatch",
    ):
        LangGraphAnalysisRunner(graph, checkpoint_meta=meta).run(
            _request(),
            _access_context(),
        )

    graph.invoke.assert_not_called()


# --- 恢复与幂等（既有能力证明） ----------------------------------------


def test_duplicate_approval_resume_has_no_terminal_side_effect() -> None:
    graph = Mock()
    graph.get_state.side_effect = [
        SimpleNamespace(
            values=_pending_state(),
            next=("request_approval",),
        ),
        SimpleNamespace(
            values={
                **_pending_state(),
                "approval_status": ApprovalStatus.APPROVED,
            },
            next=(),
        ),
    ]
    graph.invoke.return_value = _successful_state()
    runner = LangGraphAnalysisRunner(graph)
    resolution = ApprovalResolutionRequest(decision="approve", reason="ok")

    runner.resume_approval(_REQUEST_ID, resolution, _admin_context())

    with pytest.raises(ValueError, match="approval request is not pending"):
        runner.resume_approval(_REQUEST_ID, resolution, _admin_context())

    graph.invoke.assert_called_once()


def test_sse_reconnect_reuses_existing_result() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values=_successful_state(), next=())
    store = Mock()
    store.claim.return_value = _claim(
        RequestClaimStatus.EXISTING,
        RequestRunStatus.COMPLETED,
    )

    outcome = LangGraphAnalysisRunner(graph, request_store=store).run(
        _request(),
        _access_context(),
    )

    assert outcome.status is AnalysisResultStatus.SUCCEEDED
    graph.invoke.assert_not_called()


def test_restart_recovers_evidence_and_sql() -> None:
    state = _successful_state()
    state["prepared_sql"] = prepare_safe_sql(
        "SELECT refund_id FROM refunds LIMIT 5",
        max_rows=5,
        access_role=AccessRole.ANALYST,
    )
    state["retrieved_context"] = [
        RetrievalEvidence(source_id="evidence:trend:v1", content="退款趋势"),
    ]
    graph = Mock()
    graph.get_state.return_value = Mock(values=state, next=())

    outcome = LangGraphAnalysisRunner(graph).get_status(
        _REQUEST_ID,
        _access_context(),
    )

    assert outcome.status is AnalysisResultStatus.SUCCEEDED
    assert outcome.evidence_source_ids == ("evidence:trend:v1",)


def test_get_status_rejects_wrong_viewer() -> None:
    graph = Mock()
    graph.get_state.return_value = Mock(values=_pending_state(), next=())

    with pytest.raises(
        PermissionError,
        match="analysis request belongs to another user",
    ):
        LangGraphAnalysisRunner(graph).get_status(
            _REQUEST_ID,
            AccessContext(user_id="OTHER", role=AccessRole.ANALYST),
        )


# --- 审批恢复重新校验归属 ----------------------------------------------


def test_checkpoint_resume_revalidates_requester() -> None:
    graph = Mock()
    values = _pending_state()
    values["user_id"] = "REQ-B"
    graph.get_state.return_value = SimpleNamespace(
        values=values,
        next=("request_approval",),
    )
    meta = InMemoryCheckpointMetaStore()
    meta.save(CheckpointMeta(request_id=_REQUEST_ID, user_id="REQ-A"))

    with pytest.raises(
        PermissionError,
        match="checkpoint belongs to another user",
    ):
        LangGraphAnalysisRunner(graph, checkpoint_meta=meta).resume_approval(
            _REQUEST_ID,
            ApprovalResolutionRequest(decision="approve", reason="ok"),
            _admin_context(),
        )

    graph.invoke.assert_not_called()
