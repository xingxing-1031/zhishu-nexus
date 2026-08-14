from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentResponse,
    AgentReview,
    AgentStep,
    AgentTaskStatus,
    KnowledgeEvidenceView,
)


def test_agent_response_supports_unified_agent_metadata() -> None:
    response = AgentResponse(
        request_id="REQ-1",
        conversation_id="CONV-1",
        status=AgentTaskStatus.SUCCEEDED,
        agent_mode=AgentMode.KNOWLEDGE,
        agents=("knowledge_agent", "review_agent"),
        answer="根据企业制度，差旅申请需要提前审批。",
        agent_steps=(
            AgentStep(
                agent="knowledge_agent",
                task="检索企业制度证据",
                status=AgentTaskStatus.SUCCEEDED,
            ),
        ),
        knowledge_evidence=(
            KnowledgeEvidenceView(
                source_id="travel-policy@1.0#approval",
                title="差旅管理制度",
                version="1.0",
                quote="出差前应提交申请并完成审批。",
                score=0.92,
            ),
        ),
        review=AgentReview(
            passed=True,
            checks={"knowledge_evidence_present": True},
        ),
    )

    assert response.agent_mode is AgentMode.KNOWLEDGE
    assert response.knowledge_evidence[0].source_id.startswith("travel-policy")
