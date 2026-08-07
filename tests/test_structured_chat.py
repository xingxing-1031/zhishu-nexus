import json

import httpx

from retail_analytics_agent.structured_chat import (
    StructuredChatClient,
    StructuredChatProtocol,
)


def test_openai_compatible_chat_requests_json_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "qwen-plus"
        assert payload["temperature"] == 0
        assert payload["response_format"] == {"type": "json_object"}
        assert "JSON Schema" in payload["messages"][1]["content"]
        assert json.loads(payload["messages"][2]["content"]) == {
            "question": "查询销售额"
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"supported":true}'}}
                ]
            },
        )

    http_client = httpx.Client(
        base_url="https://dashscope.example/v1",
        headers={"Authorization": "Bearer test-secret"},
        transport=httpx.MockTransport(handler),
    )

    content = StructuredChatClient(
        http_client,
        StructuredChatProtocol.OPENAI_COMPATIBLE,
    ).complete_json(
        model="qwen-plus",
        system_prompt="判断是否支持",
        user_payload={"question": "查询销售额"},
        response_schema={
            "type": "object",
            "properties": {"supported": {"type": "boolean"}},
        },
        timeout_seconds=30,
    )

    assert content == '{"supported":true}'
