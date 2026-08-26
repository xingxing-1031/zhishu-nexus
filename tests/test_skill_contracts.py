from __future__ import annotations

from retail_analytics_agent.agent_models import AgentRequest, AgentTaskStatus, SkillId
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.knowledge_adapter import FixtureKnowledgeAdapter
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisResponse,
    AnalysisResultStatus,
    ChartSpec,
    ChartType,
)
from retail_analytics_agent.skills import (
    SkillDefinition,
    SkillRegistry,
    default_skill_registry,
    evaluate_completion,
)
from retail_analytics_agent.task_planner import TaskPlanner


def _skill(required_evidence: tuple[str, ...] = ()) -> SkillDefinition:
    return SkillDefinition(
        id=SkillId.REFUND_DIAGNOSIS,
        description="测试用退款诊断",
        required_tools=("sql.query",),
        completion_criteria=("退款趋势数据",),
        output_schema=("executive_summary", "findings"),
        required_evidence=required_evidence,
    )


def _custom_registry(required_evidence: tuple[str, ...]) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(_skill(required_evidence))
    return registry


def test_evaluate_completion_satisfied_when_every_evidence_is_present() -> None:
    skill = _skill(("metric.refund_rate.v1", "query:r1"))
    completion = evaluate_completion(
        skill,
        evidence_ids=("query:r1", "metric.refund_rate.v1"),
    )
    assert completion.satisfied is True
    assert completion.missing == ()


def test_evaluate_completion_reports_missing_evidence() -> None:
    skill = _skill(("metric.refund_rate.v1", "policy:refund:v1"))
    completion = evaluate_completion(
        skill,
        evidence_ids=("query:r1", "metric.refund_rate.v1"),
    )
    assert completion.satisfied is False
    assert completion.missing == ("policy:refund:v1",)


def test_evaluate_completion_matches_evidence_by_prefix() -> None:
    skill = _skill(("metric.refund_rate",))
    completion = evaluate_completion(
        skill,
        evidence_ids=("query:r1", "metric.refund_rate.v1"),
    )
    assert completion.satisfied is True


def test_evaluate_completion_satisfied_when_no_evidence_required() -> None:
    skill = _skill()
    completion = evaluate_completion(skill, evidence_ids=())
    assert completion.satisfied is True


class FakeAnalysisRunner:
    def run(self, request, access_context):
        return AnalysisResponse(
            request_id=request.request_id,
            status=AnalysisResultStatus.SUCCEEDED,
            access_role=access_context.role,
            answer="最近30天华东渠道退款率为 0.12。",
            plan=AnalysisPlan(
                analysis_goal="退款率趋势",
                metrics=["refund_rate"],
                dimensions=["channel"],
                time_range={"days": 30},
                limit=10,
            ),
            rows=[{"channel": "华东", "refund_rate": "0.12"}],
            chart_spec=ChartSpec(
                chart_type=ChartType.BAR,
                title="退款率趋势",
                x_field="channel",
                y_fields=("refund_rate",),
            ),
            evidence_source_ids=("metric.refund_rate.v1",),
            retry_count=0,
            trace=("plan", "retrieve", "execute_sql", "summarize"),
        )


def _service(required_evidence: tuple[str, ...]) -> EnterpriseAgentService:
    return EnterpriseAgentService(
        analysis_runner=FakeAnalysisRunner(),
        context_builder=ContextBuilder(InMemoryConversationStore()),
        task_planner=TaskPlanner(_custom_registry(required_evidence)),
        knowledge=FixtureKnowledgeAdapter(()),
        knowledge_departments=("admin",),
        mcp_client=None,
    )


def test_agent_service_degrades_when_skill_evidence_requirement_unmet() -> None:
    response = _service(("metric.sentinel.missing",)).run(
        AgentRequest(
            request_id="r-missing-evidence",
            conversation_id="c-missing-evidence",
            user_id="u1",
            question="分析最近30天退款率",
            include_knowledge=False,
        ),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    assert response.status is AgentTaskStatus.DEGRADED
    assert any(
        "完成条件要求的证据未全部获得" in item
        for item in response.limitations
    )
    assert response.report is not None
    assert any(
        "完成条件要求的证据未全部获得" in item
        for item in response.report.limitations
    )


def test_agent_service_succeeds_when_skill_evidence_requirement_is_met() -> None:
    response = _service(("metric.refund_rate.v1",)).run(
        AgentRequest(
            request_id="r-met-evidence",
            conversation_id="c-met-evidence",
            user_id="u1",
            question="分析最近30天退款率",
            include_knowledge=False,
        ),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    assert response.status is AgentTaskStatus.SUCCEEDED
    assert response.report is not None
    assert "metric.refund_rate.v1" in response.report.data_evidence


def test_default_skills_have_no_hard_evidence_requirement() -> None:
    assert all(
        skill.required_evidence == ()
        for skill in default_skill_registry().all()
    )
