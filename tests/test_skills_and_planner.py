import pytest

from retail_analytics_agent.agent_models import SkillId
from retail_analytics_agent.skills import (
    SkillDefinition,
    SkillRegistry,
    default_skill_registry,
)
from retail_analytics_agent.task_planner import TaskPlanner, TaskPlanningError


def test_default_registry_contains_four_explicit_skills() -> None:
    registry = default_skill_registry()
    assert {item.id for item in registry.all()} == set(SkillId)
    assert all(item.required_tools for item in registry.all())


@pytest.mark.parametrize(
    ("question", "skill"),
    [
        ("最近30天退款率为什么变化", SkillId.REFUND_DIAGNOSIS),
        ("比较抖音和门店渠道销售额", SkillId.CHANNEL_COMPARISON),
        ("哪些商品销量最高", SkillId.PRODUCT_ANALYSIS),
        ("生成本周经营周报", SkillId.WEEKLY_REPORT),
    ],
)
def test_registry_routes_business_questions(question: str, skill: SkillId) -> None:
    route = default_skill_registry().route(question)
    assert route.skill is not None
    assert route.skill.id is skill
    assert route.refused is False


def test_registry_refuses_unknown_or_destructive_questions() -> None:
    registry = default_skill_registry()
    assert registry.route("帮我写一条 SQL 删除订单").refused is True
    assert registry.route("帮我分析员工满意度").refused is True


def test_registry_reuses_last_skill_for_follow_up() -> None:
    route = default_skill_registry().route("继续看上面的变化", {"last_skill": "refund_diagnosis"})
    assert route.skill is not None
    assert route.skill.id is SkillId.REFUND_DIAGNOSIS


def test_planner_fallback_has_bounded_refund_plan() -> None:
    plan = TaskPlanner(default_skill_registry()).plan("分析退款率变化", max_steps=3)
    assert plan.skill_id is SkillId.REFUND_DIAGNOSIS
    assert len(plan.subtasks) == 3
    assert all(item.required_tools for item in plan.subtasks)


def test_planner_rejects_invalid_budget_and_unknown_scope() -> None:
    planner = TaskPlanner(default_skill_registry())
    with pytest.raises(TaskPlanningError, match="between 1 and 30"):
        planner.plan("分析退款", max_steps=0)
    with pytest.raises(TaskPlanningError, match="no registered skill"):
        planner.plan("分析员工满意度")


def test_registry_rejects_duplicate_definition() -> None:
    registry = SkillRegistry()
    definition = SkillDefinition(
        id=SkillId.REFUND_DIAGNOSIS,
        description="refund",
        required_tools=("sql.query",),
        completion_criteria=("data",),
        output_schema=("findings",),
    )
    registry.register(definition)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(definition)
