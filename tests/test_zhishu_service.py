from datetime import UTC, datetime

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentTaskStatus,
    OperationsReport,
    ReportFinding,
)
from retail_analytics_agent.agent_runs import InMemoryAgentRunStore
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.general_agent import GeneralAgentResult
from retail_analytics_agent.knowledge_adapter import KnowledgeEvidence
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.supervisor import Supervisor
from retail_analytics_agent.zhishu_service import (
    ZhishuAgentService,
    _data_only_question,
)


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
    def __init__(self):
        self.calls = 0

    def answer(self, *_args, **_kwargs):
        self.calls += 1
        return GeneralAgentResult(status=AgentTaskStatus.SUCCEEDED, answer="普通回答")


class FailingGeneral:
    def answer(self, *_args, **_kwargs):
        raise RuntimeError("postgresql://secret@internal:5432/private")


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

    def run(self, request, _access, *, persist_context=True):
        assert persist_context is False
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


def _service(data=None, *, general=None, run_store=None):
    return ZhishuAgentService(
        data_agent=data or _context_service(),
        supervisor=Supervisor(),
        general_agent=general or FakeGeneral(),
        knowledge=FakeKnowledge(),
        answerer=FakeAnswerer(),
        run_store=run_store or InMemoryAgentRunStore(),
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


def test_general_request_persists_original_question_and_final_answer_once() -> None:
    service = _service()

    service.run(
        _request("你是谁？"),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    record = service.data_agent.context_builder.store.get("c1", "u1")
    assert record is not None
    assert [(turn.role, turn.content) for turn in record.turns] == [
        ("user", "你是谁？"),
        ("assistant", "普通回答"),
    ]
    assert "last_agent_mode=general" in record.confirmed_constraints


def test_collaboration_persists_original_question_and_final_synthesis_once() -> None:
    data = FakeData()
    service = _service(data)
    question = "结合退款数据和售后制度给出复盘"

    service.run(
        _request(question),
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )

    record = data.context_builder.store.get("c1", "u1")
    assert record is not None
    assert [(turn.role, turn.content) for turn in record.turns] == [
        ("user", question),
        ("assistant", "基于已验证证据的结论。"),
    ]
    assert "last_agent_mode=collaboration" in record.confirmed_constraints


def test_completed_request_is_replayed_without_duplicate_agent_execution() -> None:
    general = FakeGeneral()
    service = _service(general=general)
    request = _request("你是谁？")
    access = AccessContext(user_id="u1", role=AccessRole.ANALYST)

    first = service.run(request, access)
    second = service.run(request, access)

    assert second == first
    assert general.calls == 1
    record = service.data_agent.context_builder.store.get("c1", "u1")
    assert record is not None
    assert len(record.turns) == 2


def test_stream_error_does_not_expose_internal_exception_text() -> None:
    service = _service(general=FailingGeneral())

    events = list(
        service.stream(
            _request("你是谁？"),
            AccessContext(user_id="u1", role=AccessRole.ANALYST),
        )
    )

    assert events[-1].event.value == "error"
    assert "postgresql://" not in events[-1].message
    stored = service.run_store.get(
        "r1",
        AccessContext(user_id="u1", role=AccessRole.ANALYST),
    )
    assert stored is not None
    assert stored.status is AgentTaskStatus.FAILED
    assert stored.failure_reason == events[-1].message


def test_running_request_returns_typed_status_without_reexecution() -> None:
    store = InMemoryAgentRunStore()
    request = _request("你是谁？")
    access = AccessContext(user_id="u1", role=AccessRole.ANALYST)
    store.claim(request, access, AgentMode.GENERAL, False)
    general = FakeGeneral()
    service = _service(general=general, run_store=store)

    response = service.run(request, access)

    assert response.status is AgentTaskStatus.RUNNING
    assert response.agent_mode is AgentMode.GENERAL
    assert general.calls == 0
