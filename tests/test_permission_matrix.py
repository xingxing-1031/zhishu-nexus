from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from retail_analytics_agent.access_control import (
    AccessPolicy,
    AuthorizationAction,
    PermissionAuditLog,
    authorize,
)
from retail_analytics_agent.analysis_service import LangGraphAnalysisRunner
from retail_analytics_agent.knowledge_adapter import (
    FixtureKnowledgeAdapter,
    KnowledgeEvidence,
    KnowledgeQuery,
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
)
from retail_analytics_agent.workflow import create_initial_state


def _analyst() -> AccessContext:
    return AccessContext(user_id="USER-001", role=AccessRole.ANALYST)


def _admin() -> AccessContext:
    return AccessContext(user_id="ADMIN-001", role=AccessRole.ADMIN)


def _restricted_policy(*datasets: str) -> AccessPolicy:
    return AccessPolicy(authorized_datasets=frozenset(datasets))


def _expired_policy() -> AccessPolicy:
    return AccessPolicy(
        authorized_datasets=frozenset({"ds-a"}),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )


def _dataset_request(dataset_id: str = "ds-a") -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-DS-001",
        user_id="USER-001",
        question="分析数据集指标",
        max_rows=10,
        dataset_id=dataset_id,
        dataset_version=1,
    )


def _successful_state() -> dict:
    state = create_initial_state(_dataset_request())
    state.update(
        {
            "plan": AnalysisPlan(
                analysis_goal="数据集指标",
                metrics=["sales_amount"],
                dimensions=["channel"],
            ),
            "sql_valid": True,
            "query_rows": [{"channel": "京东", "sales_amount": "11300.00"}],
            "final_answer": "京东渠道销售额为 11300.00 元。",
            "chart_spec": ChartSpec(
                chart_type="bar",
                title="数据集指标",
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


# --- authorize 单元决策 ------------------------------------------------


def test_admin_can_resume_approval() -> None:
    decision = authorize(
        _admin(),
        AuthorizationAction.APPROVAL_RESUME,
        "approval:REQ-001",
    )
    assert decision.allowed is True


def test_analyst_cannot_resume_approval() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.APPROVAL_RESUME,
        "approval:REQ-001",
    )
    assert decision.allowed is False
    assert decision.reason == "approval resume requires admin role"


def test_dataset_allowed_when_whitelist_contains() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.DATASET_SELECT,
        "dataset:ds-a",
        policy=_restricted_policy("ds-a"),
    )
    assert decision.allowed is True


def test_dataset_denied_when_whitelist_excludes() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.DATASET_SELECT,
        "dataset:ds-b",
        policy=_restricted_policy("ds-a"),
    )
    assert decision.allowed is False
    assert decision.reason == "dataset not authorized"


def test_dataset_allowed_without_policy() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.DATASET_SELECT,
        "dataset:any",
    )
    assert decision.allowed is True


def test_expired_policy_denies_everything() -> None:
    decision = authorize(
        _admin(),
        AuthorizationAction.DATASET_SELECT,
        "dataset:ds-a",
        policy=_expired_policy(),
    )
    assert decision.allowed is False
    assert decision.reason == "policy expired"


def test_trace_view_allowed_for_owner() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.TRACE_VIEW,
        "trace:USER-001:REQ-001",
    )
    assert decision.allowed is True


def test_trace_view_denied_for_stranger() -> None:
    stranger = AccessContext(user_id="OTHER", role=AccessRole.ANALYST)
    decision = authorize(
        stranger,
        AuthorizationAction.TRACE_VIEW,
        "trace:USER-001:REQ-001",
    )
    assert decision.allowed is False
    assert decision.reason == "trace belongs to another user"


def test_trace_view_allowed_for_admin() -> None:
    decision = authorize(
        _admin(),
        AuthorizationAction.TRACE_VIEW,
        "trace:USER-001:REQ-001",
    )
    assert decision.allowed is True


# --- 链路集成：入口 / 审批恢复重新授权 --------------------------------


def test_run_rejects_unauthorized_dataset_at_entry() -> None:
    graph = Mock()
    runner = LangGraphAnalysisRunner(
        graph,
        access_policy=_restricted_policy("ds-a"),
    )

    with pytest.raises(PermissionError, match="dataset not authorized"):
        runner.run(_dataset_request("ds-b"), _analyst())

    graph.invoke.assert_not_called()


def test_run_allows_authorized_dataset() -> None:
    graph = Mock()
    graph.invoke.return_value = _successful_state()
    runner = LangGraphAnalysisRunner(
        graph,
        access_policy=_restricted_policy("ds-a"),
    )

    outcome = runner.run(_dataset_request("ds-a"), _analyst())

    assert outcome.status is AnalysisResultStatus.SUCCEEDED
    graph.invoke.assert_called_once()


def test_resume_approval_reauthorizes_dataset() -> None:
    graph = Mock()
    graph.get_state.return_value = SimpleNamespace(
        values={
            "user_id": "USER-001",
            "access_role": AccessRole.ANALYST,
            "dataset_id": "ds-b",
            "approval_status": ApprovalStatus.PENDING,
        },
        next=("request_approval",),
    )
    runner = LangGraphAnalysisRunner(
        graph,
        access_policy=_restricted_policy("ds-a"),
    )

    with pytest.raises(PermissionError, match="dataset not authorized"):
        runner.resume_approval(
            "REQ-001",
            ApprovalResolutionRequest(decision="approve", reason="ok"),
            _admin(),
        )

    graph.invoke.assert_not_called()


def test_run_audits_entry_authorization() -> None:
    audit = PermissionAuditLog()
    graph = Mock()
    graph.invoke.return_value = _successful_state()
    runner = LangGraphAnalysisRunner(
        graph,
        access_policy=_restricted_policy("ds-a"),
        permission_audit=audit,
    )

    runner.run(_dataset_request("ds-a"), _analyst())

    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.allowed is True
    assert entry.action == "dataset.select"
    assert entry.resource == "dataset:ds-a"
    assert entry.policy_version == "1.0"


# --- RAG 召回前 pre-filter ---------------------------------------------


def _evidence(source_id: str, permissions: tuple[str, ...]) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_id=source_id,
        title="退款制度",
        version="v1",
        quote="退款需在七日内申请",
        score=0.9,
        permissions=permissions,
    )


def _rag_adapter() -> FixtureKnowledgeAdapter:
    return FixtureKnowledgeAdapter((
        _evidence("e:analyst", ("analyst",)),
        _evidence("e:admin", ("admin",)),
        _evidence("e:public", ()),
    ))


def test_rag_excludes_evidence_without_permission() -> None:
    result = _rag_adapter().retrieve(
        KnowledgeQuery(query="制度", user_id="u1", role="analyst", top_k=10)
    )
    source_ids = {item.source_id for item in result}
    assert "e:analyst" in source_ids
    assert "e:public" in source_ids
    assert "e:admin" not in source_ids


def test_rag_does_not_leak_unauthorized_evidence_on_no_match() -> None:
    result = _rag_adapter().retrieve(
        KnowledgeQuery(query="不存在的词", user_id="u1", role="analyst", top_k=10)
    )
    source_ids = {item.source_id for item in result}
    assert "e:admin" not in source_ids


def test_admin_can_read_analyst_evidence() -> None:
    result = _rag_adapter().retrieve(
        KnowledgeQuery(query="制度", user_id="admin", role="admin", top_k=10)
    )
    source_ids = {item.source_id for item in result}
    assert "e:analyst" in source_ids
    assert "e:admin" in source_ids


def test_analyst_cannot_read_admin_only_evidence() -> None:
    adapter = FixtureKnowledgeAdapter((_evidence("e:admin", ("admin",)),))
    result = adapter.retrieve(
        KnowledgeQuery(query="制度", user_id="u1", role="analyst", top_k=10)
    )
    assert result == ()


def test_public_evidence_is_visible_to_all_roles() -> None:
    adapter = FixtureKnowledgeAdapter((_evidence("e:public", ()),))
    result = adapter.retrieve(
        KnowledgeQuery(query="制度", user_id="u1", role="analyst", top_k=10)
    )
    assert result[0].source_id == "e:public"


# --- 收窄默认放行（fail-closed 补强） -----------------------------------


def test_rag_retrieve_denied_until_rule_configured() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.RAG_RETRIEVE,
        "kb-doc:retreat-policy-v3",
    )
    assert decision.allowed is False
    assert decision.reason == "authorization rule not configured for this action"


def test_evidence_return_denied_until_rule_configured() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.EVIDENCE_RETURN,
        "evidence:doc:7",
    )
    assert decision.allowed is False
    assert decision.reason == "authorization rule not configured for this action"


def test_unknown_action_denied_by_default() -> None:
    decision = authorize(
        _analyst(),
        "report.export",
        "export:weekly-summary",
    )
    assert decision.allowed is False
    assert decision.reason == "no authorization rule matched this resource"


def test_authorization_decision_records_purpose() -> None:
    decision = authorize(
        _analyst(),
        AuthorizationAction.DATASET_SELECT,
        "dataset:ds-a",
        policy=_restricted_policy("ds-a"),
        purpose="review-audit",
    )
    assert decision.purpose == "review-audit"
