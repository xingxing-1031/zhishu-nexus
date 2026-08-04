from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from retail_analytics_agent.access_control import denied_columns_for_role
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisDimension,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisSort,
    RetrievalEvidence,
    SortDirection,
)


class ModelInvocationError(RuntimeError):
    """Stable error for unavailable or invalid model responses."""


class AnalysisPlanner(Protocol):
    def plan(self, question: str, *, max_rows: int) -> AnalysisPlan: ...


class SQLGenerator(Protocol):
    def generate(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        evidence: Sequence[RetrievalEvidence],
        access_role: AccessRole,
        validation_error: str | None = None,
    ) -> str: ...


class ResultSummarizer(Protocol):
    def summarize(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        rows: Sequence[dict[str, object]],
    ) -> str: ...


class _OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class _OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _OllamaMessage


class _GeneratedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1)


class _GeneratedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)


class _ModelFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: AnalysisFilterField
    operator: AnalysisFilterOperator
    values: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_equals_value(self) -> "_ModelFilter":
        if (
            self.operator is AnalysisFilterOperator.EQUALS
            and len(self.values) != 1
        ):
            raise ValueError("equals filter requires exactly one value")
        return self


class _ModelAnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_goal: str = Field(min_length=1, max_length=500)
    metrics: list[AnalysisMetric] = Field(min_length=1, max_length=5)
    dimensions: list[AnalysisDimension] = Field(default_factory=list, max_length=5)
    filters: list[_ModelFilter] = Field(default_factory=list, max_length=10)
    time_range_days: int = Field(ge=0, le=365)
    sort: list[AnalysisSort] = Field(default_factory=list, max_length=5)
    limit: int = Field(ge=1, le=1000)

    def to_analysis_plan(self) -> AnalysisPlan:
        return AnalysisPlan(
            analysis_goal=self.analysis_goal,
            metrics=self.metrics,
            dimensions=self.dimensions,
            filters=[
                {
                    "field": item.field,
                    "operator": item.operator,
                    "value": (
                        item.values[0]
                        if item.operator is AnalysisFilterOperator.EQUALS
                        else item.values
                    ),
                }
                for item in self.filters
            ],
            time_range=(
                {"days": self.time_range_days}
                if self.time_range_days > 0
                else None
            ),
            sort=self.sort,
            limit=self.limit,
        )


def _planner_response_schema(max_rows: int) -> dict[str, object]:
    metric_values = [item.value for item in AnalysisMetric]
    dimension_values = [item.value for item in AnalysisDimension]
    filter_field_values = [item.value for item in AnalysisFilterField]
    filter_operator_values = [item.value for item in AnalysisFilterOperator]
    direction_values = [item.value for item in SortDirection]
    return {
        "type": "object",
        "properties": {
            "analysis_goal": {"type": "string"},
            "metrics": {
                "type": "array",
                "items": {"type": "string", "enum": metric_values},
                "minItems": 1,
                "maxItems": 5,
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": dimension_values},
                "maxItems": 5,
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": filter_field_values,
                        },
                        "operator": {
                            "type": "string",
                            "enum": filter_operator_values,
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                    "required": ["field", "operator", "values"],
                    "additionalProperties": False,
                },
                "maxItems": 10,
            },
            "time_range_days": {
                "type": "integer",
                "minimum": 0,
                "maximum": 365,
            },
            "sort": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": [*metric_values, *dimension_values],
                        },
                        "direction": {
                            "type": "string",
                            "enum": direction_values,
                        },
                    },
                    "required": ["field", "direction"],
                    "additionalProperties": False,
                },
                "maxItems": 5,
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": max_rows,
            },
        },
        "required": [
            "analysis_goal",
            "metrics",
            "dimensions",
            "filters",
            "time_range_days",
            "sort",
            "limit",
        ],
        "additionalProperties": False,
    }


def _chat_json(
    client: httpx.Client,
    *,
    model: str,
    system_prompt: str,
    user_payload: dict[str, object],
    response_schema: dict[str, object] | str,
) -> str:
    try:
        response = client.post(
            "/api/chat",
            json={
                "model": model,
                "stream": False,
                "think": False,
                "format": response_schema,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            user_payload,
                            ensure_ascii=False,
                            default=str,
                        ),
                    },
                ],
            },
        )
        response.raise_for_status()
        return _OllamaChatResponse.model_validate(
            response.json()
        ).message.content
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip()
        raise ModelInvocationError(
            "Ollama model invocation failed: "
            f"HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        raise ModelInvocationError(f"Ollama model invocation failed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class OllamaAnalysisPlanner:
    client: httpx.Client
    model: str = "qwen3:4b"

    def plan(self, question: str, *, max_rows: int) -> AnalysisPlan:
        if not question.strip():
            raise ValueError("question must not be empty")
        if max_rows < 1:
            raise ValueError("max_rows must be positive")

        content = _chat_json(
            self.client,
            model=self.model,
            system_prompt=(
                "你是零售分析规划器。把用户问题转换为给定 JSON Schema，"
                "只能使用 Schema 中允许的指标、维度、筛选和排序字段。"
                "计划只表达用户意图，不猜测 SQL、表、字段或 JOIN。"
                "用户没有明确筛选条件时 filters 必须为空；指标固定业务规则会由检索证据补充。"
                "时间范围只能写入 time_range_days，不能写成 filter；没有时间范围时填 0。"
            ),
            user_payload={"question": question, "max_rows": max_rows},
            response_schema=_planner_response_schema(max_rows),
        )
        try:
            plan = _ModelAnalysisPlan.model_validate_json(
                content
            ).to_analysis_plan()
        except (ValidationError, ValueError) as exc:
            raise ModelInvocationError(
                f"Ollama planner returned an invalid analysis plan: {exc}"
            ) from exc
        if plan.limit > max_rows:
            raise ModelInvocationError(
                "Ollama planner returned a limit greater than max_rows"
            )
        return plan


@dataclass(frozen=True, slots=True)
class OllamaSQLGenerator:
    client: httpx.Client
    model: str = "qwen3:4b"

    def generate(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        evidence: Sequence[RetrievalEvidence],
        access_role: AccessRole,
        validation_error: str | None = None,
    ) -> str:
        if not evidence:
            raise ValueError("retrieval evidence is required for SQL generation")

        content = _chat_json(
            self.client,
            model=self.model,
            system_prompt=(
                "你是 PostgreSQL 只读 SQL 生成器。只输出一条 SELECT 或 WITH 查询。"
                "必须严格使用分析计划表达本次意图，并严格使用检索证据中的公式、"
                "固定筛选、表、字段和批准的 JOIN。禁止 SELECT *，禁止写操作，"
                "禁止使用证据中没有出现的表、字段和关系。若提供了上一次安全校验错误，"
                "必须修正该错误。SELECT 输出中的指标和维度必须使用分析计划枚举值作为别名，"
                "例如 channel 和 sales_amount，供后续图表规格安全引用。不要解释 SQL。"
            ),
            user_payload={
                "question": question,
                "analysis_plan": plan.model_dump(mode="json"),
                "retrieval_evidence": [
                    item.model_dump(mode="json") for item in evidence
                ],
                "access_role": access_role.value,
                "forbidden_columns": [
                    f"{table}.{column}"
                    for table, column in sorted(
                        denied_columns_for_role(access_role)
                    )
                ],
                "previous_validation_error": validation_error,
            },
            response_schema=_GeneratedSQL.model_json_schema(),
        )
        try:
            sql = _GeneratedSQL.model_validate_json(content).sql.strip()
        except (ValidationError, ValueError) as exc:
            raise ModelInvocationError(
                f"Ollama SQL generator returned invalid output: {exc}"
            ) from exc
        if not sql:
            raise ModelInvocationError("Ollama SQL generator returned empty SQL")
        return sql


@dataclass(frozen=True, slots=True)
class OllamaResultSummarizer:
    client: httpx.Client
    model: str = "qwen3:4b"

    def summarize(
        self,
        *,
        question: str,
        plan: AnalysisPlan,
        rows: Sequence[dict[str, object]],
    ) -> str:
        content = _chat_json(
            self.client,
            model=self.model,
            system_prompt=(
                "你是零售分析结果解释器。只能根据给定查询结果回答，"
                "不得补造结果中不存在的数字或原因。结果为空时明确说明没有符合条件的数据。"
                "回答要简洁，并保留重要数值和分组名称。"
            ),
            user_payload={
                "question": question,
                "analysis_plan": plan.model_dump(mode="json"),
                "query_rows": list(rows),
            },
            response_schema=_GeneratedSummary.model_json_schema(),
        )
        try:
            answer = _GeneratedSummary.model_validate_json(content).answer.strip()
        except (ValidationError, ValueError) as exc:
            raise ModelInvocationError(
                f"Ollama summarizer returned invalid output: {exc}"
            ) from exc
        if not answer:
            raise ModelInvocationError("Ollama summarizer returned an empty answer")
        return answer
