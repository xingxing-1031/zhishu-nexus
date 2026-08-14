from datetime import UTC, datetime

from retail_analytics_agent.agent_models import (
    AgentRequest,
    AgentTaskStatus,
    OperationsReport,
    ReportFinding,
)
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.general_agent import GeneralAgentResult
from retail_analytics_agent.knowledge_adapter import KnowledgeEvidence
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.qixi_service import QixiAgentService, _data_only_question
from retail_analytics_agent.supervisor import Supervisor


def _request(question: str, request_id: str = "r1") -> AgentRequest:
    return AgentRequest(
        request_id=request_id,
        conversation_id="c1",
        user_id="u1",
        question=question,
    )


def _context_service() -> EnterpriseAgentService:
    return EnterpriseAgentService(
        analysis_runner=object(),
        context_builder=ContextBuilder(InMemoryConversationStore()),
        task_planner=object(),
    )


class FakeKnowledge:
    def retrieve(self, _query):
        return (
            KnowledgeEvidence(
                source_id="policy:refund@1.0",
                title="售后制度",
                version="1.0",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                quote="退款超过规则阈值需要人工复核。",
                score=0.95,
            ),
        )


class FakeGeneral:
    def answer(self, *_args, **_kwargs):
        return GeneralAgentResult(status=AgentTaskStatus.SUCCEEDED, answer="普通回答")


class FakeAnswerer:
    def answer(self, question, history, evidence, data=None):
        assert question
        assert history == []
        assert evidence
        return "基于已验证证据的结论。"


class FakeData:
    def __init__(self):
        self.context_builder = ContextBuilder(InMemoryConversationStore())
        self.calls = []

    def run(self, request, _access):
        self.calls.append(request)
        return __import__("retail_analytics_agent.agent_models", fromlist=["AgentResponse"]).AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=AgentTaskStatus.SUCCEEDED,
            answer="退款率为 4%。",
            report=OperationsReport(
                title="运营复盘",
                executive_summary="退款率为 4%。",
                findings=(ReportFinding(statement="退款率为 4%", data_evidence_ids=("query:r1",)),),
                data_evidence=("query:r1",),
            ),
        )


def _service(data=None):
    return QixiAgentService(
        data_agent=data or _context_service(),
        supervisor=Supervisor(),
        general_agent=FakeGeneral(),
        knowledge=FakeKnowledge(),
        answerer=FakeAnswerer(),
    )


def test_knowledge_request_uses_rag_without_data_agent() -> None:
    data = FakeData()
    result = _service(data).run(_request("公司的售后制度是什么"), AccessContext(user_id="u1", role=AccessRole.ANALYST))

    assert result.agent_mode.value == "knowledge"
    assert result.answer == "基于已验证证据的结论。"
    assert result.analysis is None
    assert result.knowledge_evidence[0].source_id == "policy:refund@1.0"
    assert data.calls == []


def test_collaboration_disables_rag_inside_data_agent() -> None:
    data = FakeData()
    result = _service(data).run(
        _request("结合退款数据和售后制度给出复盘"),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    assert result.agent_mode.value == "collaboration"
    assert result.review is not None and result.review.passed
    assert data.calls[0].include_knowledge is False


def test_collaboration_extracts_data_subquestion_before_sql_planning() -> None:
    assert _data_only_question("统计最近30天退款金额，并结合售后制度判断风险") == (
        "统计最近30天退款金额。"
    )
    assert _data_only_question("结合退款数据和售后制度给出复盘") == "退款数据。"
