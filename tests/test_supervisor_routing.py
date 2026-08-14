from retail_analytics_agent.agent_models import AgentMode
from retail_analytics_agent.supervisor import Supervisor


def test_routes_general_knowledge_data_and_collaboration() -> None:
    supervisor = Supervisor()

    assert supervisor.plan("现在北京时间几点").mode is AgentMode.GENERAL
    assert supervisor.plan("公司的报销制度是什么").mode is AgentMode.KNOWLEDGE
    assert supervisor.plan("最近30天退款率是多少").mode is AgentMode.DATA
    assert supervisor.plan("最近30天各退款状态的退款金额是多少").mode is AgentMode.DATA
    assert (
        supervisor.plan("结合退款数据和售后制度给出复盘").mode
        is AgentMode.COLLABORATION
    )


def test_collaboration_plan_has_bounded_specialized_agents() -> None:
    plan = Supervisor().plan("结合销售数据和采购制度形成经营复盘")

    assert [step.agent for step in plan.steps] == [
        "knowledge_agent",
        "data_agent",
        "synthesis_agent",
        "review_agent",
    ]
    assert len(plan.steps) <= 8


def test_general_plan_uses_only_general_agent() -> None:
    plan = Supervisor().plan("帮我解释一下什么是 MCP")

    assert plan.mode is AgentMode.GENERAL
    assert [step.agent for step in plan.steps] == ["general_agent"]
