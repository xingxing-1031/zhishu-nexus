from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class RequestRoute(StrEnum):
    ANALYSIS = "analysis"
    ASSISTANT = "assistant"
    CLARIFICATION = "clarification"


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    route: RequestRoute
    reason_code: str
    message: str


_IDENTITY_QUERIES = frozenset(
    {
        "你是谁",
        "你是什么",
        "介绍一下你自己",
        "你能做什么",
        "你会做什么",
        "你的功能是什么",
        "你好",
        "您好",
        "嗨",
        "hello",
        "hi",
    }
)

_AMBIGUOUS_QUERIES = frozenset(
    {
        "哪个渠道最好",
        "哪个渠道表现最好",
        "哪个品类最好",
        "哪个品类表现最好",
        "哪些商品表现最好",
        "销售情况怎么样",
        "经营情况怎么样",
        "帮我分析一下",
        "帮我看看数据",
        "分析一下",
    }
)

_CAPABILITY_MESSAGE = (
    "我是零售运营分析助手，可以基于演示数据库查询销售额、订单数、销量、"
    "退款金额、退款笔数和平均订单金额，并按渠道、商品、品类、状态或日期分析。"
    "所有数据查询都会经过只读安全校验、权限控制和审计。你可以问："
    "最近30天各渠道销售额是多少？"
)

_CLARIFICATION_MESSAGE = (
    "这个问题还缺少明确的分析口径。请补充要比较的指标和时间范围，例如："
    "最近30天哪个渠道销售额最高，或最近30天哪些商品销量最高。"
)


def _normalized_query(query: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;~～]+", "", query).casefold()


def classify_preflight_request(query: str) -> PreflightDecision | None:
    """Route deterministic conversational requests before model invocation."""

    normalized = _normalized_query(query)
    if normalized in _IDENTITY_QUERIES:
        return PreflightDecision(
            route=RequestRoute.ASSISTANT,
            reason_code="assistant_identity",
            message=_CAPABILITY_MESSAGE,
        )
    if normalized in _AMBIGUOUS_QUERIES:
        return PreflightDecision(
            route=RequestRoute.CLARIFICATION,
            reason_code="ambiguous_request",
            message=_CLARIFICATION_MESSAGE,
        )
    return None
