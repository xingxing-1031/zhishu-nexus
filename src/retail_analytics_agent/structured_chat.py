from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

import httpx
from pydantic import BaseModel, ConfigDict, Field


class StructuredChatProtocol(StrEnum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class _OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _Message


class _OpenAIChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _Message


class _OpenAIChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choices: list[_OpenAIChoice] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class StructuredChatClient:
    client: httpx.Client
    protocol: StructuredChatProtocol = StructuredChatProtocol.OLLAMA

    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, object],
        response_schema: dict[str, object] | str,
        timeout_seconds: float,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
        if self.protocol is StructuredChatProtocol.OLLAMA:
            response = self.client.post(
                "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "think": False,
                    "format": response_schema,
                    "options": {"temperature": 0},
                    "messages": messages,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return _OllamaChatResponse.model_validate(
                response.json()
            ).message.content

        schema_text = (
            response_schema
            if isinstance(response_schema, str)
            else json.dumps(response_schema, ensure_ascii=False)
        )
        response = self.client.post(
            "/chat/completions",
            json={
                "model": model,
                "stream": False,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    messages[0],
                    {
                        "role": "system",
                        "content": (
                            "只输出一个符合以下 JSON Schema 的 JSON 对象，"
                            f"不要输出解释或 Markdown：{schema_text}"
                        ),
                    },
                    messages[1],
                ],
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return _OpenAIChatResponse.model_validate(
            response.json()
        ).choices[0].message.content
