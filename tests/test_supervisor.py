from retail_analytics_agent.agent_models import AgentMode
from retail_analytics_agent.supervisor import Supervisor


def test_supervisor_reuses_previous_data_mode_for_elliptical_follow_up() -> None:
    plan = Supervisor().plan("再拆一下", previous_mode=AgentMode.DATA)

    assert plan.mode is AgentMode.DATA


def test_supervisor_prefers_explicit_current_intent_over_previous_mode() -> None:
    plan = Supervisor().plan(
        "公司的采购制度是什么？",
        previous_mode=AgentMode.DATA,
    )

    assert plan.mode is AgentMode.KNOWLEDGE


def test_supervisor_can_infer_follow_up_mode_from_history() -> None:
    plan = Supervisor().plan(
        "继续看看",
        history=(
            {"role": "user", "content": "统计最近30天销售额"},
            {"role": "assistant", "content": "销售额已统计。"},
        ),
    )

    assert plan.mode is AgentMode.DATA


def test_supervisor_keeps_unrelated_new_question_general() -> None:
    plan = Supervisor().plan(
        "写一首短诗",
        previous_mode=AgentMode.DATA,
    )

    assert plan.mode is AgentMode.GENERAL
