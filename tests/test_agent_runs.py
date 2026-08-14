from pathlib import Path

import pytest

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentTaskStatus,
)
from retail_analytics_agent.agent_runs import (
    AgentRunClaimStatus,
    InMemoryAgentRunStore,
    is_auditable_agent_request,
)
from retail_analytics_agent.models import AccessContext, AccessRole

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "migrations"
    / "010_agent_request_runs.sql"
)


def _request(question: str = "公司的退款制度是什么？") -> AgentRequest:
    return AgentRequest(
        request_id="REQ-AGENT-RUN-001",
        conversation_id="CONV-001",
        user_id="USER-001",
        question=question,
        max_rows=10,
    )


def _access(
    user_id: str = "USER-001",
    role: AccessRole = AccessRole.ANALYST,
) -> AccessContext:
    return AccessContext(user_id=user_id, role=role)


def test_agent_run_migration_defines_durable_result_and_audit_contract() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "CREATE TABLE agent_request_runs" in sql
    assert "request_id TEXT PRIMARY KEY" in sql
    assert "request_fingerprint CHAR(64) NOT NULL" in sql
    assert "response_payload JSONB" in sql
    assert "auditable BOOLEAN NOT NULL" in sql
    assert "tool_names TEXT[] NOT NULL" in sql
    assert "evidence_count INTEGER NOT NULL" in sql


def test_agent_run_store_replays_same_request_and_rejects_changed_input() -> None:
    store = InMemoryAgentRunStore()

    first = store.claim(_request(), _access(), AgentMode.KNOWLEDGE, True)
    repeated = store.claim(_request(), _access(), AgentMode.KNOWLEDGE, True)
    changed = store.claim(
        _request("公司的采购制度是什么？"),
        _access(),
        AgentMode.KNOWLEDGE,
        True,
    )

    assert first.status is AgentRunClaimStatus.NEW
    assert repeated.status is AgentRunClaimStatus.EXISTING
    assert changed.status is AgentRunClaimStatus.CONFLICT


def test_agent_run_store_recovers_completed_response_for_owner_or_admin() -> None:
    store = InMemoryAgentRunStore()
    request = _request()
    store.claim(request, _access(), AgentMode.KNOWLEDGE, True)
    response = AgentResponse(
        request_id=request.request_id,
        conversation_id=request.conversation_id,
        status=AgentTaskStatus.SUCCEEDED,
        agent_mode=AgentMode.KNOWLEDGE,
        answer="制度要求退款申请经过复核。",
    )

    store.complete(response, duration_ms=125)

    owner = store.get(request.request_id, _access())
    admin = store.get(
        request.request_id,
        _access("ADMIN-001", AccessRole.ADMIN),
    )
    assert owner is not None and owner.response == response
    assert owner.status is AgentTaskStatus.SUCCEEDED
    assert owner.duration_ms == 125
    assert admin == owner
    with pytest.raises(PermissionError):
        store.get(request.request_id, _access("USER-OTHER"))


def test_business_audit_excludes_chat_but_includes_enterprise_security_attempts() -> None:
    assert not is_auditable_agent_request("你好，介绍一下你自己", AgentMode.GENERAL)
    assert not is_auditable_agent_request("重庆现在天气如何", AgentMode.GENERAL)
    assert is_auditable_agent_request("公司的报销制度是什么", AgentMode.KNOWLEDGE)
    assert is_auditable_agent_request("查询最近30天销售额", AgentMode.DATA)
    assert is_auditable_agent_request("删除企业数据库里的订单", AgentMode.GENERAL)

