from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from retail_analytics_agent.metric_retrieval import (
    MAX_METRIC_RESULTS,
    MetricRetriever,
)
from retail_analytics_agent.models import AnalysisMetric


class DomainGateError(RuntimeError):
    """Stable error for unavailable or invalid domain-gate responses."""


class MetricDomainGate(Protocol):
    def is_supported(self, query: str) -> bool: ...


class _OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class _OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _OllamaMessage


class _DomainDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool


@dataclass(frozen=True, slots=True)
class OllamaMetricDomainGate:
    """Classifies whether a query belongs to the supported metric domain."""

    client: httpx.Client
    model: str = "qwen3:4b"

    def is_supported(self, query: str) -> bool:
        if not query.strip():
            return False
        try:
            response = self.client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "format": _DomainDecision.model_json_schema(),
                    "options": {"temperature": 0},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是零售指标能力边界分类器。系统只支持六类结果："
                                "销售额、订单数、销售件数、退款金额、退款笔数、平均"
                                "订单金额。用户使用同义表达也算支持。库存、客户隐私"
                                "数据、天气、写作、编程、推荐等其他问题一律不支持。"
                                "你只判断是否属于这六类能力，不要尝试回答问题。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"question": query},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
            )
            response.raise_for_status()
            content = _OllamaChatResponse.model_validate(
                response.json()
            ).message.content
            return _DomainDecision.model_validate_json(content).supported
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise DomainGateError(f"Ollama domain gate failed: {exc}") from exc


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
        if not self.gate.is_supported(query):
            return ()
        return tuple(self.retriever.search(query, top_k=top_k))
