from retail_analytics_agent.agent_models import (
    ContextSnapshot,
    SkillId,
    Subtask,
    TaskPlan,
    ToolResult,
)
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.operations_workflow import OperationsWorkflow
from retail_analytics_agent.tool_registry import ToolRegistry, ToolSpec


def _plan() -> TaskPlan:
    return TaskPlan(
        goal="退款诊断",
        skill_id=SkillId.REFUND_DIAGNOSIS,
        subtasks=(
            Subtask(id="trend", description="数据趋势", required_tools=("sql.query",)),
            Subtask(id="policy", description="制度证据", required_tools=("knowledge.search",)),
        ),
        completion_criteria=("数据", "制度"),
        max_steps=4,
    )


def _context() -> ContextSnapshot:
    return ContextSnapshot(conversation_id="c1", task_goal="退款诊断", token_budget=1000)


def test_operations_workflow_runs_sql_and_knowledge_and_composes_report() -> None:
    registry = ToolRegistry()
    registry.register(ToolSpec(name="sql.query", description="sql"), lambda p, c: ToolResult(
        tool_name="sql.query", status="succeeded", evidence_ids=("query:refund-trend",), payload={"rows": []}
    ))
    registry.register(ToolSpec(name="knowledge.search", description="rag"), lambda p, c: ToolResult(
        tool_name="knowledge.search", status="succeeded", evidence_ids=("policy:refund:v1",), payload={"quote": "制度"}
    ))
    state = OperationsWorkflow(registry).run(
        request_id="r1", conversation_id="c1", question="退款率为什么变化",
        access_context=AccessContext(user_id="u1", role=AccessRole.ANALYST),
        task_plan=_plan(), context=_context(), findings=("退款率需要结合趋势与制度解释。",),
    )
    assert state.status == "succeeded"
    assert state.report is not None
    assert state.report.data_evidence == ("query:refund-trend",)
    assert state.report.document_evidence == ("policy:refund:v1",)


def test_operations_workflow_refuses_when_required_tool_is_missing() -> None:
    registry = ToolRegistry()
    registry.register(ToolSpec(name="sql.query", description="sql"), lambda p, c: {"rows": []})
    state = OperationsWorkflow(registry).run(
        request_id="r1", conversation_id="c1", question="退款率为什么变化",
        access_context=AccessContext(user_id="u1", role=AccessRole.ANALYST),
        task_plan=_plan(), context=_context(),
    )
    assert state.status == "refused"
    assert state.report is not None
    assert state.report.limitations


def test_operations_workflow_respects_step_budget() -> None:
    registry = ToolRegistry()
    registry.register(ToolSpec(name="sql.query", description="sql"), lambda p, c: {"rows": []})
    state = OperationsWorkflow(registry).run(
        request_id="r1", conversation_id="c1", question="退款率为什么变化",
        access_context=AccessContext(user_id="u1", role=AccessRole.ANALYST),
        task_plan=_plan().model_copy(update={"max_steps": 1}), context=_context(),
    )
    assert state.step_count == 1
    assert state.status in {"degraded", "refused"}
