from retail_analytics_agent.agent_models import AgentRequest, AgentTaskStatus, SkillId
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.knowledge_adapter import (
    FixtureKnowledgeAdapter,
    KnowledgeEvidence,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisResponse,
    AnalysisResultStatus,
    ChartSpec,
    ChartType,
)
from retail_analytics_agent.skills import default_skill_registry
from retail_analytics_agent.task_planner import TaskPlanner


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


class FakeMcpClient:
    def discover(self):
        return ("export_operations_report",)

    def call(self, tool_name, payload):
        assert tool_name == "export_operations_report"
        assert payload["format"] == "markdown"
        return {"result": "# 企业经营分析复盘报告\n\n已导出"}


def _service() -> EnterpriseAgentService:
    return EnterpriseAgentService(
        analysis_runner=FakeAnalysisRunner(),
        context_builder=ContextBuilder(InMemoryConversationStore()),
        task_planner=TaskPlanner(default_skill_registry()),
        knowledge=FixtureKnowledgeAdapter((
            KnowledgeEvidence(
                source_id="policy:refund:v1",
                title="售后退款制度",
                version="v1",
                quote="退款申请需在七日内发起。",
                score=0.9,
                permissions=("analyst",),
            ),
        )),
        knowledge_departments=("admin",),
        mcp_client=FakeMcpClient(),
    )


def test_agent_service_combines_sql_rag_context_and_report() -> None:
    service = _service()
    response = service.run(
        AgentRequest(
            request_id="r1",
            conversation_id="c1",
            user_id="u1",
            question="最近30天退款率为什么变化？结合售后制度复盘",
        ),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    assert response.status is AgentTaskStatus.SUCCEEDED
    assert response.skill_id is SkillId.REFUND_DIAGNOSIS
    assert response.report is not None
    assert "query:r1" in response.report.data_evidence
    assert response.report.document_evidence == ("policy:refund:v1",)
    assert [item.tool_name for item in response.tool_calls] == [
        "sql.query",
        "knowledge.search",
        "report.export",
    ]
    assert response.exported_report.startswith("# 企业经营分析复盘报告")


def test_agent_service_degrades_and_updates_report_when_mcp_is_missing() -> None:
    service = _service()
    service.mcp_client = None
    service.tool_registry = None
    service.__post_init__()

    response = service.run(
        AgentRequest(
            request_id="r-mcp-missing",
            conversation_id="c-mcp-missing",
            user_id="u1",
            question="分析退款率变化并导出报告",
        ),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    assert response.status is AgentTaskStatus.DEGRADED
    assert "MCP 报告导出服务未配置。" in response.limitations
    assert response.report is not None
    assert "MCP 报告导出服务未配置。" in response.report.limitations


def test_agent_service_inherits_skill_for_follow_up() -> None:
    service = _service()
    access = AccessContext(user_id="u1", role=AccessRole.ANALYST)
    service.run(
        AgentRequest(
            request_id="r1", conversation_id="c1", user_id="u1",
            question="分析退款率变化",
        ),
        access,
    )
    response = service.run(
        AgentRequest(
            request_id="r2", conversation_id="c1", user_id="u1",
            question="继续看上面的变化",
        ),
        access,
    )
    assert response.skill_id is SkillId.REFUND_DIAGNOSIS
    assert response.context is not None
    assert response.context.confirmed_constraints == (
        "last_skill=refund_diagnosis",
    )
