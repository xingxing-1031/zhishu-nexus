import json

from retail_analytics_agent.agent_models import AgentTaskStatus
from retail_analytics_agent.general_agent import GeneralAgent


class FakeModel:
    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


class FakeMcp:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def discover(self) -> tuple[str, ...]:
        return (
            "time_now",
            "weather_current",
            "web_search",
            "web_fetch_summary",
            "exchange_rate",
        )

    def call(self, tool_name: str, payload: dict) -> dict:
        self.calls.append((tool_name, payload))
        if tool_name == "weather_current":
            return {"location": {"name": "Chongqing"}, "current": {"temperature": 31}}
        raise AssertionError(tool_name)


def test_general_agent_calls_weather_then_answers_from_tool_result() -> None:
    model = FakeModel(
        {
            "action": "tool",
            "tool_name": "weather.current",
            "arguments": {"city": "Chongqing"},
        },
        {"action": "answer", "answer": "Chongqing is currently about 31 C."},
    )
    mcp = FakeMcp()
    agent = GeneralAgent(model=model, mcp_client=mcp)

    result = agent.answer("What is the weather in Chongqing?", [], "r1", "c1", "analyst")

    assert mcp.calls == [("weather_current", {"city": "Chongqing"})]
    assert result.answer == "Chongqing is currently about 31 C."
    assert result.tool_calls[0].tool_name == "weather.current"
    assert result.tool_calls[0].status == "succeeded"


def test_general_agent_rejects_unknown_tool_without_calling_mcp() -> None:
    model = FakeModel(
        {
            "action": "tool",
            "tool_name": "database.write",
            "arguments": {},
        },
        {"answer": "I cannot run that tool.", "limitations": ["not allowlisted"]},
    )
    mcp = FakeMcp()
    result = GeneralAgent(model=model, mcp_client=mcp).answer(
        "Change the database", [], "r2", "c2", "analyst"
    )

    assert mcp.calls == []
    assert result.tool_calls[0].status == "refused"
    assert "cannot" in result.answer


def test_general_agent_can_answer_without_a_tool() -> None:
    model = FakeModel({"action": "answer", "answer": "我是知枢 AI。"})
    result = GeneralAgent(
        model=model,
        mcp_client=FakeMcp(),
    ).answer("你是谁？", [], "r3", "c3", "analyst")

    assert result.answer == "我是知枢 AI。"
    assert result.tool_calls == ()
    assert result.status is AgentTaskStatus.SUCCEEDED
    prompt = model.calls[0]["system_prompt"]
    assert "知枢 AI" in prompt
    assert "不可信" in prompt
    assert "企析" not in prompt
    assert "不要声称整个平台无法访问企业知识或经营数据" in prompt
