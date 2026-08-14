from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentStep,
    AgentStrictModel,
)


class AgentPlan(AgentStrictModel):
    mode: AgentMode
    reason: str = Field(min_length=1, max_length=300)
    steps: tuple[AgentStep, ...] = Field(min_length=1, max_length=8)


DATA_TERMS = {
    "销售额",
    "销售数据",
    "经营数据",
    "订单",
    "订单数",
    "退款率",
    "退款量",
    "退款数据",
    "商品",
    "品类",
    "渠道",
    "客单价",
    "转化率",
    "同比",
    "环比",
    "趋势",
    "经营周报",
    "经营复盘",
    "revenue",
    "sales",
    "refund rate",
    "orders",
}

KNOWLEDGE_TERMS = {
    "公司制度",
    "制度",
    "流程",
    "规定",
    "规范",
    "政策",
    "手册",
    "报销",
    "考勤",
    "请假",
    "加班",
    "入职",
    "离职",
    "采购",
    "供应商",
    "审批",
    "权限",
    "差旅",
    "发票",
    "售后制度",
    "policy",
    "rule",
    "procedure",
}


def _contains(question: str, terms: set[str]) -> bool:
    normalized = question.casefold()
    return any(term.casefold() in normalized for term in terms)


def _steps(mode: AgentMode, question: str) -> tuple[AgentStep, ...]:
    if mode is AgentMode.GENERAL:
        return (AgentStep(agent="general_agent", task=question),)
    if mode is AgentMode.KNOWLEDGE:
        return (
            AgentStep(
                agent="knowledge_agent",
                task="检索并核验企业知识证据",
            ),
            AgentStep(
                agent="review_agent",
                task="审核引用与回答边界",
            ),
        )
    if mode is AgentMode.DATA:
        return (
            AgentStep(
                agent="data_agent",
                task="查询并分析受治理的经营数据",
            ),
            AgentStep(
                agent="review_agent",
                task="审核数据证据与分析边界",
            ),
        )
    return (
        AgentStep(
            agent="knowledge_agent",
            task="检索并核验相关企业制度",
        ),
        AgentStep(
            agent="data_agent",
            task="查询并分析相关经营数据",
        ),
        AgentStep(
            agent="synthesis_agent",
            task="综合制度与数据证据形成结论",
        ),
        AgentStep(
            agent="review_agent",
            task="审核引用、数据证据与任务完整性",
        ),
    )


class Supervisor:
    """Route clear enterprise requests deterministically before model use."""

    def plan(
        self,
        question: str,
        history: Sequence[dict[str, str]] = (),
    ) -> AgentPlan:
        del history
        has_data = _contains(question, DATA_TERMS)
        has_knowledge = _contains(question, KNOWLEDGE_TERMS)
        if has_data and has_knowledge:
            mode = AgentMode.COLLABORATION
        elif has_data:
            mode = AgentMode.DATA
        elif has_knowledge:
            mode = AgentMode.KNOWLEDGE
        else:
            mode = AgentMode.GENERAL
        return AgentPlan(
            mode=mode,
            reason=f"根据企业知识与经营数据需求路由为 {mode.value}",
            steps=_steps(mode, question),
        )
