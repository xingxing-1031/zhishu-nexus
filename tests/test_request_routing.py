from datetime import datetime, timezone

import pytest

from retail_analytics_agent.request_routing import (
    RequestRoute,
    classify_preflight_request,
)


@pytest.mark.parametrize("query", ["你是谁？", "你好", "你能做什么", "你可以干嘛"])
def test_identity_and_greeting_requests_use_assistant_route(query: str) -> None:
    decision = classify_preflight_request(query)

    assert decision is not None
    assert decision.route is RequestRoute.ASSISTANT
    assert decision.reason_code == "assistant_identity"
    assert "零售运营分析助手" in decision.message


def test_time_request_uses_shanghai_time_without_analysis() -> None:
    decision = classify_preflight_request(
        "上海现在几点？",
        now=datetime(2026, 8, 10, 1, 23, tzinfo=timezone.utc),
    )

    assert decision is not None
    assert decision.route is RequestRoute.ASSISTANT
    assert decision.reason_code == "assistant_time"
    assert decision.message == "当前上海时间是 2026-08-10 09:23。"


@pytest.mark.parametrize("query", ["好吧", "好的。", "懂了", "谢谢！"])
def test_acknowledgements_do_not_enter_analysis(query: str) -> None:
    decision = classify_preflight_request(query)

    assert decision is not None
    assert decision.route is RequestRoute.ASSISTANT
    assert decision.reason_code == "assistant_acknowledgement"
    assert "继续提出零售运营分析问题" in decision.message


@pytest.mark.parametrize(
    "query",
    ["哪个渠道最好？", "经营情况怎么样", "帮我分析一下"],
)
def test_ambiguous_requests_ask_for_metric_and_time_range(query: str) -> None:
    decision = classify_preflight_request(query)

    assert decision is not None
    assert decision.route is RequestRoute.CLARIFICATION
    assert decision.reason_code == "ambiguous_request"
    assert "指标和时间范围" in decision.message


@pytest.mark.parametrize(
    "query",
    [
        "你好，帮我查最近30天各渠道销售额",
        "什么东西最好卖？",
        "最近30天各渠道销售额是多少？",
    ],
)
def test_business_questions_continue_to_analysis(query: str) -> None:
    assert classify_preflight_request(query) is None
