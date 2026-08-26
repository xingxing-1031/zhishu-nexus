from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Protocol

from pydantic import Field

from retail_analytics_agent.access_control import (
    requested_sensitive_columns,
    requests_role_elevation,
    requests_write_operation,
)
from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentStep,
    AgentStrictModel,
    RoutingDecision,
)
from retail_analytics_agent.models import AccessRole


class StructuredModel(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, object],
        response_schema: dict[str, object] | str,
        timeout_seconds: float,
    ) -> str: ...


class AgentPlan(AgentStrictModel):
    mode: AgentMode
    reason: str = Field(min_length=1, max_length=300)
    steps: tuple[AgentStep, ...] = Field(min_length=1, max_length=8)
    confidence: float = Field(default=1.0, ge=0, le=1)
    reason_code: str = Field(
        default="deterministic_route",
        min_length=1,
        max_length=80,
    )
    missing_information: tuple[str, ...] = Field(default=(), max_length=12)
    refused: bool = False


DATA_TERMS = {
    "销售额",
    "销售数据",
    "经营数据",
    "订单",
    "订单数",
    "退款率",
    "退款量",
    "退款数据",
    "退款金额",
    "退款状态",
    "退款笔数",
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

FOLLOW_UP_TERMS = {
    "继续",
    "再",
    "上面",
    "刚才",
    "这个",
    "那个",
    "换成",
    "改成",
    "改为",
    "拆一下",
    "展开",
    "为什么",
    "然后呢",
    "接着",
}

_AMBIGUOUS_TERMS = (
    "哪个渠道最好",
    "哪个品类最好",
    "哪些商品表现最好",
    "销售情况怎么样",
    "经营情况怎么样",
    "帮我分析一下",
    "帮我看看数据",
    "分析一下",
    "怎么样",
)

_CLARIFICATION_MESSAGE = (
    "这个问题还缺少明确的分析口径。请补充要比较的指标、时间范围或具体对象，"
    "例如：最近30天哪个渠道销售额最高，或最近30天哪些商品销量最高。"
)

_LLM_ROUTING_PROMPT = (
    "你是知枢企业运营分析的路由器。只输出一个符合 JSON Schema 的 JSON 对象，"
    "不要输出解释或 Markdown。根据用户问题判断："
    "1. 是否涉及经营数据（销售额、订单、退款、商品、渠道、品类等）→ data；"
    "2. 是否只涉及企业制度/知识 → knowledge；"
    "3. 是否同时需要数据和制度 → collaboration；"
    "4. 其他通用问题 → general。"
    "confidence 表示对路由判断的确信度（0-1）。"
    "如果问题缺少比较指标、时间范围等必要条件，在 missing_information 中列出具体缺口，"
    "并降低 confidence。subtasks 列出你认为需要执行的子任务（字符串，最多 8 个）。"
    "reason_code 用一个简短英文标识这次路由的原因。"
)

_LLM_ROUTING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": [item.value for item in AgentMode]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "subtasks": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "reason_code": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["mode", "confidence", "reason_code", "missing_information"],
}


def _contains(question: str, terms: set[str]) -> bool:
    normalized = question.casefold()
    return any(term.casefold() in normalized for term in terms)


def _is_ambiguous(question: str) -> bool:
    normalized = question.casefold()
    return any(term.casefold() in normalized for term in _AMBIGUOUS_TERMS)


def _mode_from_history(
    history: Sequence[dict[str, str]],
) -> AgentMode | None:
    for item in reversed(history):
        content = item.get("content", "")
        has_data = _contains(content, DATA_TERMS)
        has_knowledge = _contains(content, KNOWLEDGE_TERMS)
        if has_data and has_knowledge:
            return AgentMode.COLLABORATION
        if has_data:
            return AgentMode.DATA
        if has_knowledge:
            return AgentMode.KNOWLEDGE
    return None


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


DatasetChecker = Callable[[str, int | None], str | None]


def _apply_rules(
    question: str,
    *,
    access_role: AccessRole | None,
    dataset_id: str | None,
    dataset_version: int | None,
    dataset_checker: DatasetChecker | None,
) -> RoutingDecision | None:
    if not question.strip():
        return RoutingDecision(
            mode=AgentMode.GENERAL,
            confidence=1.0,
            reason_code="empty_question",
            reason="问题内容为空，无法开始分析。",
            refused=True,
        )
    if requests_write_operation(question):
        return RoutingDecision(
            mode=AgentMode.GENERAL,
            confidence=1.0,
            reason_code="write_operation_refused",
            reason="该请求涉及写操作或破坏性操作，超出受控分析范围。",
            refused=True,
        )
    if access_role is not None and requests_role_elevation(question, access_role):
        return RoutingDecision(
            mode=AgentMode.GENERAL,
            confidence=1.0,
            reason_code="role_elevation_refused",
            reason="当前身份无权以更高级别角色执行该请求。",
            refused=True,
        )
    if requested_sensitive_columns(question):
        return RoutingDecision(
            mode=AgentMode.DATA,
            confidence=0.95,
            reason_code="sensitive_columns_approval",
            reason="请求涉及敏感字段，将路由到数据 Agent 并进入审批流程。",
        )
    if dataset_id is not None:
        if dataset_checker is None:
            return RoutingDecision(
                mode=AgentMode.DATA,
                confidence=0.5,
                reason_code="dataset_unavailable",
                missing_information=("数据集状态服务不可用",),
                reason="无法校验所选数据集状态。",
            )
        status = dataset_checker(dataset_id, dataset_version)
        if status is None:
            return RoutingDecision(
                mode=AgentMode.DATA,
                confidence=1.0,
                reason_code="dataset_not_found",
                reason=f"数据集 {dataset_id} 不存在。",
                refused=True,
            )
        if status != "ready":
            return RoutingDecision(
                mode=AgentMode.DATA,
                confidence=1.0,
                reason_code="dataset_not_ready",
                reason=f"数据集 {dataset_id} 当前状态为 {status}，不可用于分析。",
                refused=True,
            )
    return None


def _keyword_decision(
    question: str,
    history: Sequence[dict[str, str]],
    previous_mode: AgentMode | None,
) -> RoutingDecision | None:
    has_data = _contains(question, DATA_TERMS)
    has_knowledge = _contains(question, KNOWLEDGE_TERMS)
    if has_data and has_knowledge:
        return RoutingDecision(
            mode=AgentMode.COLLABORATION,
            confidence=0.9,
            reason_code="keyword_route",
            reason="检测到经营数据与企业制度双重需求。",
        )
    if has_data:
        if _is_ambiguous(question):
            return RoutingDecision(
                mode=AgentMode.DATA,
                confidence=0.3,
                reason_code="ambiguous_request",
                missing_information=("需要明确比较的指标", "需要明确时间范围"),
                reason="请求命中数据需求但口径不够明确。",
            )
        return RoutingDecision(
            mode=AgentMode.DATA,
            confidence=0.9,
            reason_code="keyword_route",
            reason="检测到经营数据需求。",
        )
    if has_knowledge:
        return RoutingDecision(
            mode=AgentMode.KNOWLEDGE,
            confidence=0.9,
            reason_code="keyword_route",
            reason="检测到企业制度需求。",
        )
    if _contains(question, FOLLOW_UP_TERMS):
        mode = previous_mode or _mode_from_history(history) or AgentMode.GENERAL
        if previous_mode is None and mode is AgentMode.GENERAL:
            return RoutingDecision(
                mode=AgentMode.GENERAL,
                confidence=0.4,
                reason_code="ambiguous_follow_up",
                missing_information=("需要补充任务背景",),
                reason="追问缺少可推断的任务上下文。",
            )
        return RoutingDecision(
            mode=mode,
            confidence=0.7,
            reason_code="follow_up_context",
            reason="根据对话上下文路由为追问模式。",
        )
    return None


def _fallback_decision(
    question: str,
    history: Sequence[dict[str, str]],
    previous_mode: AgentMode | None,
) -> RoutingDecision:
    del question, history, previous_mode
    return RoutingDecision(
        mode=AgentMode.GENERAL,
        confidence=0.5,
        reason_code="general_fallback",
        reason="未检测到明确的企业制度或经营数据需求，交给通用助手。",
    )


def _llm_decision(
    model: StructuredModel,
    *,
    model_name: str,
    timeout_seconds: float,
    question: str,
    history: Sequence[dict[str, str]],
    access_role: AccessRole | None,
    dataset_id: str | None,
) -> RoutingDecision | None:
    payload: dict[str, object] = {
        "question": question,
        "history": list(history)[-6:],
        "access_role": access_role.value if access_role else None,
        "dataset_id": dataset_id,
        "candidate_modes": [item.value for item in AgentMode],
    }
    try:
        raw = model.complete_json(
            model=model_name,
            system_prompt=_LLM_ROUTING_PROMPT,
            user_payload=payload,
            response_schema=_LLM_ROUTING_SCHEMA,
            timeout_seconds=timeout_seconds,
        )
        data = json.loads(raw)
        return RoutingDecision(
            mode=AgentMode(data["mode"]),
            confidence=float(data["confidence"]),
            subtasks=tuple(data.get("subtasks") or ()),
            missing_information=tuple(data.get("missing_information") or ()),
            reason_code=str(data.get("reason_code") or "llm_route"),
            reason=str(data.get("reason") or "基于语义意图的结构化路由。"),
        )
    except Exception:
        return None


class Supervisor:
    """Route enterprise requests through rules, keyword, and LLM layers.

    Four-stage pipeline: deterministic rules -> keyword intent -> structured
    LLM routing -> code-level validation. Low-confidence decisions carry
    missing_information so the caller can ask a targeted clarification.
    """

    def __init__(
        self,
        *,
        model: StructuredModel | None = None,
        model_name: str = "qwen3",
        timeout_seconds: float = 30,
        dataset_checker: DatasetChecker | None = None,
        min_confidence: float = 0.6,
    ):
        self._model = model
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._dataset_checker = dataset_checker
        self._min_confidence = min_confidence

    def route(
        self,
        question: str,
        history: Sequence[dict[str, str]] = (),
        *,
        previous_mode: AgentMode | None = None,
        access_role: AccessRole | None = None,
        dataset_id: str | None = None,
        dataset_version: int | None = None,
    ) -> RoutingDecision:
        rule = _apply_rules(
            question,
            access_role=access_role,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            dataset_checker=self._dataset_checker,
        )
        if rule is not None:
            return rule
        keyword = _keyword_decision(question, history, previous_mode)
        if self._model is None:
            return keyword or _fallback_decision(question, history, previous_mode)
        if (
            keyword is not None
            and keyword.confidence >= self._min_confidence
            and not keyword.missing_information
        ):
            return keyword
        llm = _llm_decision(
            self._model,
            model_name=self._model_name,
            timeout_seconds=self._timeout_seconds,
            question=question,
            history=history,
            access_role=access_role,
            dataset_id=dataset_id,
        )
        if llm is not None:
            return llm
        return keyword or _fallback_decision(question, history, previous_mode)

    def plan(
        self,
        question: str,
        history: Sequence[dict[str, str]] = (),
        *,
        previous_mode: AgentMode | None = None,
        access_role: AccessRole | None = None,
        dataset_id: str | None = None,
        dataset_version: int | None = None,
    ) -> AgentPlan:
        decision = self.route(
            question,
            history,
            previous_mode=previous_mode,
            access_role=access_role,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )
        safe_question = question.strip() or "处理请求"
        steps = _steps(decision.mode, safe_question)
        if decision.refused:
            return AgentPlan(
                mode=decision.mode,
                reason=decision.reason or "请求被拒绝。",
                steps=steps,
                confidence=decision.confidence,
                reason_code=decision.reason_code,
                missing_information=decision.missing_information,
                refused=True,
            )
        low_confidence = decision.confidence < self._min_confidence
        return AgentPlan(
            mode=decision.mode,
            reason=decision.reason or f"根据意图路由为 {decision.mode.value}",
            steps=steps,
            confidence=decision.confidence,
            reason_code=decision.reason_code,
            missing_information=(
                decision.missing_information if low_confidence else ()
            ),
        )
