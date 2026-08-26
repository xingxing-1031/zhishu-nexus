from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from pydantic import Field

from retail_analytics_agent.agent_models import AgentStrictModel, SkillId, ToolRisk
from retail_analytics_agent.models import AccessRole


class SkillDefinition(AgentStrictModel):
    id: SkillId
    version: str = Field(default="1.0", min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=500)
    required_inputs: tuple[str, ...] = Field(default=(), max_length=12)
    required_tools: tuple[str, ...] = Field(min_length=1, max_length=12)
    completion_criteria: tuple[str, ...] = Field(min_length=1, max_length=12)
    refusal_conditions: tuple[str, ...] = Field(default=(), max_length=12)
    output_schema: tuple[str, ...] = Field(min_length=1, max_length=12)
    allowed_roles: tuple[AccessRole, ...] = Field(
        default=(AccessRole.ANALYST, AccessRole.ADMIN),
        min_length=1,
        max_length=4,
    )
    risk: ToolRisk = ToolRisk.MEDIUM
    required_evidence: tuple[str, ...] = Field(default=(), max_length=8)


@dataclass(frozen=True)
class CompletionEvaluation:
    satisfied: bool
    missing: tuple[str, ...] = ()


def evaluate_completion(
    definition: SkillDefinition,
    *,
    evidence_ids: Sequence[str],
) -> CompletionEvaluation:
    missing = tuple(
        item
        for item in definition.required_evidence
        if not any(evidence.startswith(item) for evidence in evidence_ids)
    )
    return CompletionEvaluation(satisfied=not missing, missing=missing)


@dataclass(frozen=True)
class SkillRoute:
    skill: SkillDefinition | None
    reason: str
    refused: bool = False


@dataclass
class SkillRegistry:
    _definitions: dict[SkillId, SkillDefinition] = field(default_factory=dict)

    def register(self, definition: SkillDefinition) -> None:
        if definition.id in self._definitions:
            raise ValueError(f"skill already registered: {definition.id.value}")
        self._definitions[definition.id] = definition

    def get(self, skill_id: SkillId) -> SkillDefinition:
        try:
            return self._definitions[skill_id]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {skill_id.value}") from exc

    def all(self) -> tuple[SkillDefinition, ...]:
        return tuple(self._definitions.values())

    def route(self, question: str, context: Mapping[str, str] | None = None) -> SkillRoute:
        normalized = question.casefold().strip()
        if not normalized:
            return SkillRoute(None, "empty question", refused=True)
        if any(term in normalized for term in ("删除", "清空", "drop table", "delete from", "update ")):
            return SkillRoute(None, "write or destructive operation is outside agent scope", refused=True)

        candidates: list[tuple[int, SkillId, str]] = []
        for skill_id, terms, reason in _ROUTE_RULES:
            score = sum(1 for term in terms if term.casefold() in normalized)
            if score:
                candidates.append((score, skill_id, reason))
        if not candidates and context:
            previous = context.get("last_skill", "").strip()
            if previous:
                try:
                    skill_id = SkillId(previous)
                except ValueError:
                    pass
                else:
                    return SkillRoute(self.get(skill_id), "inherited from conversation context")
        if not candidates:
            return SkillRoute(None, "no registered skill matches the request", refused=True)
        _score, skill_id, reason = max(candidates, key=lambda item: item[0])
        return SkillRoute(self.get(skill_id), reason)


_ROUTE_RULES: tuple[tuple[SkillId, tuple[str, ...], str], ...] = (
    (
        SkillId.REFUND_DIAGNOSIS,
        ("退款", "退货", "refund", "售后", "拒付"),
        "matched refund and after-sales terms",
    ),
    (
        SkillId.CHANNEL_COMPARISON,
        ("渠道", "平台", "channel", "来源", "门店"),
        "matched channel comparison terms",
    ),
    (
        SkillId.PRODUCT_ANALYSIS,
        ("商品", "产品", "品类", "sku", "product", "销量"),
        "matched product analysis terms",
    ),
    (
        SkillId.WEEKLY_REPORT,
        ("周报", "周报告", "经营复盘", "经营报告", "weekly", "复盘"),
        "matched recurring report terms",
    ),
)


def default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(SkillDefinition(
        id=SkillId.REFUND_DIAGNOSIS,
        version="1.0",
        description="解释退款率、退款金额或售后异常，并结合制度证据给出原因。",
        required_inputs=("时间范围", "退款指标"),
        required_tools=(
            "catalog.retrieve",
            "sql.query",
            "knowledge.search",
            "chart.build",
            "report.compose",
            "report.export",
        ),
        completion_criteria=("退款趋势数据", "渠道或商品拆解", "售后制度证据", "引用完整"),
        refusal_conditions=("敏感原文未审批", "缺少可验证数据", "请求写操作"),
        output_schema=("executive_summary", "findings", "data_evidence", "document_evidence"),
        allowed_roles=(AccessRole.ANALYST, AccessRole.ADMIN),
    ))
    registry.register(SkillDefinition(
        id=SkillId.CHANNEL_COMPARISON,
        version="1.0",
        description="比较不同渠道的销售、订单和退款表现。",
        required_inputs=("时间范围", "渠道维度", "比较指标"),
        required_tools=(
            "catalog.retrieve",
            "sql.query",
            "knowledge.search",
            "chart.build",
            "report.compose",
        ),
        completion_criteria=("统一时间范围", "渠道维度对比", "数据口径说明"),
        refusal_conditions=("指标口径不一致", "缺少时间范围", "请求写操作"),
        output_schema=("executive_summary", "findings", "data_evidence"),
        allowed_roles=(AccessRole.ANALYST, AccessRole.ADMIN),
    ))
    registry.register(SkillDefinition(
        id=SkillId.PRODUCT_ANALYSIS,
        version="1.0",
        description="分析商品或品类的销量、销售额和退款表现。",
        required_inputs=("时间范围", "商品或品类维度", "指标"),
        required_tools=(
            "catalog.retrieve",
            "sql.query",
            "knowledge.search",
            "chart.build",
            "report.compose",
        ),
        completion_criteria=("商品或品类拆解", "指标排序", "数据证据"),
        refusal_conditions=("未知商品字段", "缺少指标", "请求写操作"),
        output_schema=("executive_summary", "findings", "data_evidence"),
        allowed_roles=(AccessRole.ANALYST, AccessRole.ADMIN),
    ))
    registry.register(SkillDefinition(
        id=SkillId.WEEKLY_REPORT,
        version="1.0",
        description="生成有时间边界、带数据和制度引用的经营周报。",
        required_inputs=("周时间边界", "核心经营指标"),
        required_tools=(
            "catalog.retrieve",
            "sql.query",
            "knowledge.search",
            "chart.build",
            "report.compose",
            "report.export",
        ),
        completion_criteria=("本周与上周对比", "异常项", "行动建议有证据", "报告可导出"),
        refusal_conditions=("日期范围不明确", "证据不足", "请求写操作"),
        output_schema=("executive_summary", "findings", "charts", "limitations"),
        allowed_roles=(AccessRole.ANALYST, AccessRole.ADMIN),
        risk=ToolRisk.HIGH,
    ))
    return registry
