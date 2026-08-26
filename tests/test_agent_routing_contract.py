from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentTaskStatus,
    SkillId,
    Subtask,
    TaskPlan,
)
from retail_analytics_agent.agent_runs import InMemoryAgentRunStore
from retail_analytics_agent.agent_service import EnterpriseAgentService
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.context_store import InMemoryConversationStore
from retail_analytics_agent.general_agent import GeneralAgentResult
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.skills import default_skill_registry
from retail_analytics_agent.supervisor import Supervisor
from retail_analytics_agent.zhishu_service import ZhishuAgentService


def _access() -> AccessContext:
    return AccessContext(user_id="u1", role=AccessRole.ANALYST)


class _FakeGeneral:
    def answer(self, *_args, **_kwargs) -> GeneralAgentResult:
        return GeneralAgentResult(
            status=AgentTaskStatus.SUCCEEDED,
            answer="普通回答",
        )


class _FakeAnswerer:
    def answer(self, question, history, evidence, data=None):
        assert question
        assert evidence
        return "基于证据的结论。"


class _FakeKnowledge:
    def retrieve(self, _query):
        return ()


class _FakeData:
    def __init__(self) -> None:
        self.context_builder = ContextBuilder(InMemoryConversationStore())
        self.calls: list[AgentRequest] = []

    def run(self, request, _access, *, persist_context=True):
        assert persist_context is False
        self.calls.append(request)
        return AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=AgentTaskStatus.SUCCEEDED,
            answer="销售额已统计。",
        )


def _context_service() -> EnterpriseAgentService:
    return EnterpriseAgentService(
        analysis_runner=object(),
        context_builder=ContextBuilder(InMemoryConversationStore()),
        task_planner=object(),
    )


def _request(question: str, request_id: str = "r1") -> AgentRequest:
    return AgentRequest(
        request_id=request_id,
        conversation_id="c1",
        user_id="u1",
        question=question,
    )


def _service(
    supervisor: Supervisor | None = None,
    data=None,
) -> ZhishuAgentService:
    return ZhishuAgentService(
        data_agent=data or _context_service(),
        supervisor=supervisor or Supervisor(),
        general_agent=_FakeGeneral(),
        knowledge=_FakeKnowledge(),
        answerer=_FakeAnswerer(),
        run_store=InMemoryAgentRunStore(),
    )


class TestSupervisorRuleLayer:
    def test_empty_question_is_refused(self) -> None:
        plan = Supervisor().plan("   ")

        assert plan.refused is True
        assert plan.reason_code == "empty_question"

    def test_write_operation_is_refused(self) -> None:
        plan = Supervisor().plan("帮我删除订单表")

        assert plan.refused is True
        assert plan.reason_code == "write_operation_refused"

    def test_role_elevation_is_refused_for_analyst(self) -> None:
        plan = Supervisor().plan(
            "以管理员身份查看全部",
            access_role=AccessRole.ANALYST,
        )

        assert plan.refused is True
        assert plan.reason_code == "role_elevation_refused"

    def test_admin_role_is_not_blocked_by_elevation_rule(self) -> None:
        plan = Supervisor().plan(
            "以管理员身份查看全部",
            access_role=AccessRole.ADMIN,
        )

        assert plan.refused is False

    def test_sensitive_columns_route_to_data_approval(self) -> None:
        decision = Supervisor().route(
            "查询退款的具体原因",
            access_role=AccessRole.ANALYST,
        )

        assert decision.mode is AgentMode.DATA
        assert decision.reason_code == "sensitive_columns_approval"
        assert decision.refused is False

    def test_unknown_dataset_is_refused(self) -> None:
        supervisor = Supervisor(dataset_checker=lambda _id, _v: None)

        decision = supervisor.route("分析销售额", dataset_id="d1")

        assert decision.refused is True
        assert decision.reason_code == "dataset_not_found"

    def test_non_ready_dataset_is_refused(self) -> None:
        supervisor = Supervisor(dataset_checker=lambda _id, _v: "needs_mapping")

        decision = supervisor.route("分析销售额", dataset_id="d1")

        assert decision.refused is True
        assert decision.reason_code == "dataset_not_ready"

    def test_ready_dataset_passes_rules(self) -> None:
        supervisor = Supervisor(dataset_checker=lambda _id, _v: "ready")

        decision = supervisor.route("分析销售额", dataset_id="d1")

        assert decision.refused is False
        assert decision.mode is AgentMode.DATA

    def test_dataset_checker_unavailable_is_clarification(self) -> None:
        decision = Supervisor().route("分析销售额", dataset_id="d1")

        assert decision.refused is False
        assert decision.reason_code == "dataset_unavailable"
        assert decision.missing_information


class TestSupervisorStructuredRouting:
    def test_routing_decision_is_structured(self) -> None:
        decision = Supervisor().route("公司的报销制度是什么")

        assert decision.mode is AgentMode.KNOWLEDGE
        assert 0 <= decision.confidence <= 1
        assert decision.reason_code
        assert isinstance(decision.subtasks, tuple)
        assert isinstance(decision.missing_information, tuple)

    def test_keyword_route_is_high_confidence(self) -> None:
        decision = Supervisor().route("最近30天各渠道退款率是多少")

        assert decision.mode is AgentMode.DATA
        assert decision.confidence >= 0.6
        assert decision.reason_code == "keyword_route"

    def test_ambiguous_data_request_carries_missing_information(self) -> None:
        plan = Supervisor().plan("哪个渠道最好")

        assert plan.mode is AgentMode.DATA
        assert plan.confidence < 0.6
        assert plan.missing_information

    def test_plan_carries_structured_decision_fields(self) -> None:
        plan = Supervisor().plan("结合退款数据和售后制度给出复盘")

        assert plan.mode is AgentMode.COLLABORATION
        assert plan.confidence >= 0.6
        assert plan.reason_code
        assert plan.missing_information == ()
        assert plan.refused is False


class TestSupervisorLLMRouting:
    def test_llm_overrides_low_confidence_keyword(self) -> None:
        model = Mock()
        model.complete_json.return_value = (
            '{"mode":"knowledge","confidence":0.9,'
            '"reason_code":"llm_route","missing_information":[]}'
        )

        plan = Supervisor(model=model).plan("哪个渠道最好")

        assert plan.mode is AgentMode.KNOWLEDGE
        assert plan.confidence == 0.9

    def test_llm_failure_degrades_to_keyword(self) -> None:
        model = Mock()
        model.complete_json.side_effect = RuntimeError("ollama down")

        plan = Supervisor(model=model).plan("哪个渠道最好")

        assert plan.mode is AgentMode.DATA
        assert plan.missing_information

    def test_llm_high_confidence_ignores_missing_information(self) -> None:
        model = Mock()
        model.complete_json.return_value = (
            '{"mode":"data","confidence":0.95,'
            '"reason_code":"llm_route","missing_information":["需要时间范围"]}'
        )

        plan = Supervisor(model=model).plan("哪个渠道最好")

        assert plan.mode is AgentMode.DATA
        assert plan.confidence == 0.95
        assert plan.missing_information == ()

    def test_llm_unstructured_output_is_ignored(self) -> None:
        model = Mock()
        model.complete_json.return_value = "not json at all"

        plan = Supervisor(model=model).plan("哪个渠道最好")

        assert plan.mode is AgentMode.DATA


class TestSkillContract:
    def test_skills_declare_version_inputs_and_roles(self) -> None:
        for definition in default_skill_registry().all():
            assert definition.version
            assert definition.required_inputs
            assert definition.allowed_roles
            assert AccessRole.ANALYST in definition.allowed_roles
            assert "sql.query" in definition.required_tools


class TestTaskPlanDependencyValidation:
    def test_rejects_dependency_on_unknown_subtask(self) -> None:
        with pytest.raises(ValidationError, match="unknown id"):
            TaskPlan(
                goal="diagnose refunds",
                skill_id=SkillId.REFUND_DIAGNOSIS,
                subtasks=(
                    Subtask(id="a", description="a", depends_on=("missing",)),
                ),
                completion_criteria=("data",),
            )

    def test_rejects_dependency_cycle(self) -> None:
        with pytest.raises(ValidationError, match="cycle"):
            TaskPlan(
                goal="diagnose refunds",
                skill_id=SkillId.REFUND_DIAGNOSIS,
                subtasks=(
                    Subtask(id="a", description="a", depends_on=("b",)),
                    Subtask(id="b", description="b", depends_on=("a",)),
                ),
                completion_criteria=("data",),
            )

    def test_accepts_acyclic_dependencies(self) -> None:
        plan = TaskPlan(
            goal="diagnose refunds",
            skill_id=SkillId.REFUND_DIAGNOSIS,
            subtasks=(
                Subtask(id="a", description="a"),
                Subtask(id="b", description="b", depends_on=("a",)),
            ),
            completion_criteria=("data",),
        )

        assert len(plan.subtasks) == 2


class TestZhishuRoutingConsumption:
    def test_write_operation_is_refused_at_service_level(self) -> None:
        response = _service().run(
            _request("帮我删除订单数据", request_id="r9"),
            _access(),
        )

        assert response.status is AgentTaskStatus.REFUSED
        assert response.limitations == ("write_operation_refused",)

    def test_ambiguous_question_asks_clarification(self) -> None:
        response = _service().run(
            _request("哪个渠道最好", request_id="r10"),
            _access(),
        )

        assert response.status is AgentTaskStatus.REFUSED
        assert "需要补充" in response.answer
        assert response.limitations == ("ambiguous_request",)

    def test_non_ready_dataset_is_refused_at_service_level(self) -> None:
        service = _service(
            Supervisor(dataset_checker=lambda _id, _v: "needs_mapping")
        )
        request = _request("分析销售额", request_id="r11").model_copy(
            update={"dataset_id": "d1"}
        )

        response = service.run(request, _access())

        assert response.status is AgentTaskStatus.REFUSED
        assert response.limitations == ("dataset_not_ready",)

    def test_ready_dataset_enters_execution_and_forwards_dataset_id(self) -> None:
        data = _FakeData()
        service = _service(
            Supervisor(dataset_checker=lambda _id, _v: "ready"),
            data=data,
        )
        request = _request("分析销售额", request_id="r12").model_copy(
            update={"dataset_id": "d1"}
        )

        response = service.run(request, _access())

        assert response.status is not AgentTaskStatus.REFUSED
        assert data.calls
        assert data.calls[0].dataset_id == "d1"
