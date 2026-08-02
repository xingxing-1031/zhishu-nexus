from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from retail_analytics_agent.knowledge import (
    DEFAULT_METRIC_CATALOG,
    MetricCatalog,
)
from retail_analytics_agent.metric_retrieval import (
    MAX_METRIC_RESULTS,
    MetricRetriever,
)
from retail_analytics_agent.models import AnalysisMetric


class RerankingError(RuntimeError):
    """Stable error for unavailable or invalid reranker responses."""


class MetricReranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: Sequence[AnalysisMetric],
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]: ...


class _OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class _OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _OllamaMessage


class _RerankDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_source_ids: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def validate_unique_sources(self) -> Self:
        if len(set(self.selected_source_ids)) != len(self.selected_source_ids):
            raise ValueError("selected_source_ids must not contain duplicates")
        return self


@dataclass(frozen=True, slots=True)
class OllamaLLMMetricReranker:
    """Listwise metric selector backed by an Ollama chat model."""

    client: httpx.Client
    model: str = "qwen3:0.6b"
    catalog: MetricCatalog = DEFAULT_METRIC_CATALOG

    def rerank(
        self,
        query: str,
        candidates: Sequence[AnalysisMetric],
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]:
        if not 1 <= top_k <= MAX_METRIC_RESULTS:
            raise ValueError(
                f"top_k must be between 1 and {MAX_METRIC_RESULTS}"
            )
        unique_candidates = tuple(dict.fromkeys(candidates))
        if not query.strip() or not unique_candidates:
            return ()

        definitions = [
            self.catalog.get(metric)
            for metric in unique_candidates
        ]
        source_to_metric = {
            definition.source_id: definition.metric
            for definition in definitions
        }
        candidate_payload = [
            {
                "source_id": definition.source_id,
                "name": definition.display_name,
                "aliases": list(definition.aliases),
                "description": definition.description,
            }
            for definition in definitions
        ]
        response_format = {
            "type": "object",
            "properties": {
                "selected_source_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": list(source_to_metric),
                    },
                    "uniqueItems": True,
                    "maxItems": top_k,
                }
            },
            "required": ["selected_source_ids"],
            "additionalProperties": False,
        }

        try:
            response = self.client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "format": response_format,
                    "options": {"temperature": 0},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是零售分析指标重排器。返回回答问题所需的最小充分"
                                "指标集合。只选择用户明确询问的指标，绝对不要选择仅仅"
                                "相关、可辅助分析或出现在候选列表中的指标。只有问题用"
                                "‘和’等方式明确询问多个结果时才能多选。问题不属于候选"
                                "指标能力范围时必须返回空数组。示例：‘各个平台一共成交"
                                "了多少钱’只选销售额；‘总共售出了多少个商品’只选销售"
                                "件数；‘平均每笔订单消费多少’只选平均订单金额；‘重庆"
                                "明天会下雨吗’返回空数组。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "question": query,
                                    "candidates": candidate_payload,
                                },
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
            decision = _RerankDecision.model_validate_json(content)
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise RerankingError(f"Ollama reranking failed: {exc}") from exc

        unknown_sources = set(decision.selected_source_ids) - set(source_to_metric)
        if unknown_sources:
            raise RerankingError(
                "Ollama reranking returned unknown source IDs: "
                + ", ".join(sorted(unknown_sources))
            )
        return tuple(
            source_to_metric[source_id]
            for source_id in decision.selected_source_ids[:top_k]
        )


@dataclass(frozen=True, slots=True)
class RerankedMetricRetriever:
    candidate_retriever: MetricRetriever
    reranker: MetricReranker
    candidate_k: int = 5

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[AnalysisMetric, ...]:
        if not 1 <= self.candidate_k <= MAX_METRIC_RESULTS:
            raise ValueError(
                f"candidate_k must be between 1 and {MAX_METRIC_RESULTS}"
            )
        candidates = self.candidate_retriever.search(
            query,
            top_k=self.candidate_k,
        )
        return self.reranker.rerank(query, candidates, top_k=top_k)
