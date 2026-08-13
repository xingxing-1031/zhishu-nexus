from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from retail_analytics_agent.agent_models import SkillId, Subtask, TaskPlan
from retail_analytics_agent.skills import SkillDefinition, SkillRegistry


class TaskPlannerModel(Protocol):
    def plan(
        self,
        question: str,
        skill: SkillDefinition,
        context: Mapping[str, str],
        max_steps: int,
    ) -> TaskPlan: ...


class TaskPlanningError(ValueError):
    """Raised when a task cannot be planned within the execution budget."""


@dataclass(frozen=True)
class TaskPlanner:
    registry: SkillRegistry
    model: TaskPlannerModel | None = None
    default_max_steps: int = 8

    def plan(
        self,
        question: str,
        *,
        context: Mapping[str, str] | None = None,
        max_steps: int | None = None,
    ) -> TaskPlan:
        limit = self.default_max_steps if max_steps is None else max_steps
        if limit < 1 or limit > 30:
            raise TaskPlanningError("max_steps must be between 1 and 30")
        route = self.registry.route(question, context)
        if route.refused or route.skill is None:
            raise TaskPlanningError(route.reason)
        if self.model is not None:
            planned = self.model.plan(question, route.skill, context or {}, limit)
            if planned.skill_id is not route.skill.id:
                raise TaskPlanningError("planner model changed the routed skill")
            if len(planned.subtasks) > limit or planned.max_steps > limit:
                raise TaskPlanningError("planner exceeded execution step budget")
            return planned.model_copy(update={"max_steps": limit})
        return self._fallback_plan(question, route.skill, limit)

    def _fallback_plan(
        self,
        question: str,
        skill: SkillDefinition,
        max_steps: int,
    ) -> TaskPlan:
        templates: dict[SkillId, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
            SkillId.REFUND_DIAGNOSIS: (
                ("trend", "查询退款率和退款金额趋势", ("catalog.retrieve", "sql.query")),
                ("breakdown", "按渠道和商品拆解异常来源", ("sql.query", "chart.build")),
                ("policy", "检索相关售后制度并核对口径", ("knowledge.search",)),
                ("report", "组合带引用的经营复盘报告", ("report.compose",)),
            ),
            SkillId.CHANNEL_COMPARISON: (
                ("metrics", "按统一口径查询各渠道指标", ("catalog.retrieve", "sql.query")),
                ("compare", "计算渠道差异并生成图表", ("chart.build",)),
                ("report", "输出渠道对比结论", ("report.compose",)),
            ),
            SkillId.PRODUCT_ANALYSIS: (
                ("metrics", "查询商品或品类表现", ("catalog.retrieve", "sql.query")),
                ("rank", "按指标排序并识别异常商品", ("chart.build",)),
                ("report", "输出商品分析结论", ("report.compose",)),
            ),
            SkillId.WEEKLY_REPORT: (
                ("current", "查询本周经营指标", ("catalog.retrieve", "sql.query")),
                ("previous", "查询上周指标作为对照", ("sql.query",)),
                ("evidence", "检索制度和行动建议依据", ("knowledge.search",)),
                ("report", "生成并导出带引用周报", ("chart.build", "report.compose", "report.export")),
            ),
        }
        items = templates[skill.id][:max_steps]
        if len(items) < 1:
            raise TaskPlanningError("skill has no executable subtasks")
        return TaskPlan(
            goal=question.strip(),
            skill_id=skill.id,
            subtasks=tuple(
                Subtask(id=task_id, description=description, required_tools=tools)
                for task_id, description, tools in items
            ),
            completion_criteria=skill.completion_criteria,
            max_steps=max_steps,
        )
