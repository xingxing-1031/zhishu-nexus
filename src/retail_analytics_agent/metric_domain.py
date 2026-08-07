from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from retail_analytics_agent.metric_retrieval import (
    MAX_METRIC_RESULTS,
    MetricRetriever,
)
from retail_analytics_agent.models import AnalysisMetric
from retail_analytics_agent.structured_chat import (
    StructuredChatClient,
    StructuredChatProtocol,
)


class DomainGateError(RuntimeError):
    """Stable error for unavailable or invalid domain-gate responses."""


class DomainRejectionReason(StrEnum):
    UNSUPPORTED_METRIC = "unsupported_metric"
    UNSUPPORTED_DIMENSION = "unsupported_dimension"


class DomainDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supported: bool
    reason_code: DomainRejectionReason | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "DomainDecision":
        if self.supported and self.reason_code is not None:
            raise ValueError("supported decisions must not contain a reason code")
        if not self.supported and self.reason_code is None:
            raise ValueError("unsupported decisions require a reason code")
        return self


class MetricDomainGate(Protocol):
    def classify(self, query: str) -> DomainDecision: ...


_UNSUPPORTED_METRIC_TERMS = (
    "库存",
    "存货",
    "inventory",
    "stock level",
    "毛利",
    "利润",
    "gross profit",
    "profit",
    "发货时长",
    "配送时长",
    "到货时长",
    "shipping time",
    "广告",
    "投放",
    "roi",
    "投诉",
    "客诉",
    "complaint",
)
_UNSUPPORTED_DIMENSION_TERMS = (
    "年龄",
    "年龄段",
    "性别",
    "会员等级",
    "age group",
    "gender",
)


def explicit_domain_rejection(query: str) -> DomainDecision | None:
    """Return deterministic rejections for concepts absent from the schema."""

    normalized = query.casefold()
    if any(term in normalized for term in _UNSUPPORTED_METRIC_TERMS):
        return DomainDecision(
            supported=False,
            reason_code=DomainRejectionReason.UNSUPPORTED_METRIC,
        )
    if any(term in normalized for term in _UNSUPPORTED_DIMENSION_TERMS):
        return DomainDecision(
            supported=False,
            reason_code=DomainRejectionReason.UNSUPPORTED_DIMENSION,
        )
    return None


@dataclass(frozen=True, slots=True)
class StructuredMetricDomainGate:
    """Classifies whether a query belongs to the supported metric domain."""

    client: httpx.Client
    model: str = "qwen3:4b"
    protocol: StructuredChatProtocol = StructuredChatProtocol.OLLAMA
    timeout_seconds: float = 120

    def classify(self, query: str) -> DomainDecision:
        if not query.strip():
            return DomainDecision(
                supported=False,
                reason_code=DomainRejectionReason.UNSUPPORTED_METRIC,
            )
        explicit_rejection = explicit_domain_rejection(query)
        if explicit_rejection is not None:
            return explicit_rejection
        try:
            content = StructuredChatClient(
                self.client,
                self.protocol,
            ).complete_json(
                model=self.model,
                system_prompt=(
                    "你是零售指标能力边界分类器。系统只支持六类结果："
                    "销售额、订单数、销售件数、退款金额、退款笔数、平均"
                    "订单金额；只支持渠道、商品、商品类别、订单状态、退款"
                    "状态和日期维度。用户使用同义表达也算支持。若请求的"
                    "结果指标不受支持，reason_code 返回 unsupported_metric；"
                    "若指标受支持但分组维度不受支持，返回 unsupported_dimension。"
                    "支持时 reason_code 必须为 null。你只判断能力边界，不回答问题。"
                ),
                user_payload={"question": query},
                response_schema=DomainDecision.model_json_schema(),
                timeout_seconds=self.timeout_seconds,
            )
            return DomainDecision.model_validate_json(content)
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise DomainGateError(f"Model domain gate failed: {exc}") from exc

    def is_supported(self, query: str) -> bool:
        return self.classify(query).supported


OllamaMetricDomainGate = StructuredMetricDomainGate


@dataclass(frozen=True, slots=True)
class DomainGatedMetricRetriever:
    gate: MetricDomainGate
    retriever: MetricRetriever

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]:
        if not 1 <= top_k <= MAX_METRIC_RESULTS:
            raise ValueError(
                f"top_k must be between 1 and {MAX_METRIC_RESULTS}"
            )
        if not self.gate.classify(query).supported:
            return ()
        return tuple(self.retriever.search(query, top_k=top_k))
