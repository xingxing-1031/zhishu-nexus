from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.agent_models import (
    AgentTaskStatus,
    ToolCallRecord,
)
from retail_analytics_agent.brand_identity import (
    FINAL_ANSWER_SYSTEM_PROMPT,
    GENERAL_AGENT_SYSTEM_PROMPT,
)
from retail_analytics_agent.mcp_client import McpClientError, McpToolClient


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


class ToolDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["answer", "tool"]
    tool_name: str | None = Field(default=None, max_length=80)
    arguments: dict[str, object] = Field(default_factory=dict)
    answer: str = ""


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=12000)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class GeneralAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentTaskStatus
    answer: str = ""
    tool_calls: tuple[ToolCallRecord, ...] = ()
    limitations: tuple[str, ...] = ()


TOOL_NAMES = {
    "time.now": "time_now",
    "weather.current": "weather_current",
    "web.search": "web_search",
    "web.fetch_summary": "web_fetch_summary",
    "exchange.rate": "exchange_rate",
}

TOOL_DESCRIPTIONS = {
    "time.now": "查询指定 IANA 时区的当前时间",
    "weather.current": "查询公开城市的当前天气",
    "web.search": "搜索公开新闻和网页文章",
    "web.fetch_summary": "读取公开网页正文，之后由模型总结",
    "exchange.rate": "查询公开汇率报价",
}

DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["answer", "tool"]},
        "tool_name": {"type": ["string", "null"]},
        "arguments": {"type": "object"},
        "answer": {"type": "string"},
    },
    "required": ["action", "tool_name", "arguments", "answer"],
}

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "limitations"],
}


def _input_hash(arguments: dict[str, object]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class GeneralAgent:
    model: StructuredModel
    mcp_client: McpToolClient | Any | None = None
    model_name: str = "qwen3"
    timeout_seconds: float = 60
    max_tool_calls: int = 3

    def answer(
        self,
        question: str,
        history: Sequence[dict[str, str]],
        request_id: str,
        conversation_id: str,
        access_role: str,
    ) -> GeneralAgentResult:
        tool_calls: list[ToolCallRecord] = []
        facts: list[dict[str, object]] = []
        limitations: list[str] = []
        for _step in range(self.max_tool_calls):
            decision = self._decide(
                question,
                history,
                facts,
                access_role,
            )
            if decision.action == "answer":
                answer = decision.answer.strip()
                if not answer:
                    answer = self._finalize(question, history, facts, limitations)
                return GeneralAgentResult(
                    status=(
                        AgentTaskStatus.DEGRADED
                        if limitations
                        else AgentTaskStatus.SUCCEEDED
                    ),
                    answer=answer,
                    tool_calls=tuple(tool_calls),
                    limitations=tuple(limitations),
                )
            name = decision.tool_name or ""
            if name not in TOOL_NAMES:
                tool_calls.append(
                    ToolCallRecord(
                        request_id=request_id,
                        conversation_id=conversation_id,
                        tool_name=name or "unknown",
                        input_hash=_input_hash(decision.arguments),
                        status="refused",
                        error_type="ToolNotAllowlisted",
                    )
                )
                limitations.append("请求的工具不在知枢通用工具白名单中")
                answer = self._finalize(question, history, facts, limitations)
                return GeneralAgentResult(
                    status=AgentTaskStatus.DEGRADED,
                    answer=answer,
                    tool_calls=tuple(tool_calls),
                    limitations=tuple(limitations),
                )
            if self.mcp_client is None:
                limitations.append(f"工具 {name} 未配置")
                break
            tool_calls.append(
                self._call_tool(
                    name,
                    decision.arguments,
                    request_id,
                    conversation_id,
                    facts,
                    limitations,
                )
            )
            if limitations:
                break
        if len(tool_calls) >= self.max_tool_calls:
            limitations.append("已达到通用工具调用步数上限")
        answer = self._finalize(question, history, facts, limitations)
        return GeneralAgentResult(
            status=(AgentTaskStatus.DEGRADED if limitations else AgentTaskStatus.SUCCEEDED),
            answer=answer,
            tool_calls=tuple(tool_calls),
            limitations=tuple(limitations),
        )

    def _decide(
        self,
        question: str,
        history: Sequence[dict[str, str]],
        facts: Sequence[dict[str, object]],
        access_role: str,
    ) -> ToolDecision:
        payload = {
            "question": question,
            "history": list(history)[-6:],
            "facts": list(facts)[-4:],
            "access_role": access_role,
            "tools": TOOL_DESCRIPTIONS,
        }
        raw = self.model.complete_json(
            model=self.model_name,
            system_prompt=GENERAL_AGENT_SYSTEM_PROMPT,
            user_payload=payload,
            response_schema=DECISION_SCHEMA,
            timeout_seconds=self.timeout_seconds,
        )
        return ToolDecision.model_validate_json(raw)

    def _call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        request_id: str,
        conversation_id: str,
        facts: list[dict[str, object]],
        limitations: list[str],
    ) -> ToolCallRecord:
        started = monotonic()
        input_hash = _input_hash(arguments)
        mcp_name = TOOL_NAMES[name]
        try:
            discovered = set(self.mcp_client.discover())
            if mcp_name not in discovered:
                raise McpClientError(f"tool is not discovered: {mcp_name}")
            result = self.mcp_client.call(mcp_name, arguments)
            facts.append({"tool": name, "result": result})
            return ToolCallRecord(
                request_id=request_id,
                conversation_id=conversation_id,
                tool_name=name,
                input_hash=input_hash,
                status="succeeded",
                duration_ms=int((monotonic() - started) * 1000),
            )
        except Exception as exc:
            limitations.append(f"工具 {name} 调用失败，未使用未经验证的实时信息")
            return ToolCallRecord(
                request_id=request_id,
                conversation_id=conversation_id,
                tool_name=name,
                input_hash=input_hash,
                status="failed",
                duration_ms=int((monotonic() - started) * 1000),
                error_type=type(exc).__name__,
            )

    def _finalize(
        self,
        question: str,
        history: Sequence[dict[str, str]],
        facts: Sequence[dict[str, object]],
        limitations: Sequence[str],
    ) -> str:
        raw = self.model.complete_json(
            model=self.model_name,
            system_prompt=FINAL_ANSWER_SYSTEM_PROMPT,
            user_payload={
                "question": question,
                "history": list(history)[-6:],
                "facts": list(facts)[-4:],
                "limitations": list(limitations),
            },
            response_schema=ANSWER_SCHEMA,
            timeout_seconds=self.timeout_seconds,
        )
        return FinalAnswer.model_validate_json(raw).answer.strip()
