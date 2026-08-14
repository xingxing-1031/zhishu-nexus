from datetime import UTC, datetime

import httpx
import pytest

from retail_analytics_agent.common_tools import (
    CommonToolInputError,
    CommonTools,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_time_now_defaults_to_shanghai() -> None:
    tools = CommonTools(
        _client(lambda _request: httpx.Response(500)),
        clock=lambda: datetime(2026, 8, 14, 8, 30, tzinfo=UTC),
    )

    result = tools.time_now("Asia/Shanghai")

    assert result["timezone"] == "Asia/Shanghai"
    assert result["local_time"] == "2026-08-14T16:30:00+08:00"
    assert result["source"] == "system_clock"


def test_weather_current_uses_geocoding_then_forecast() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding-api" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Chongqing",
                            "country": "China",
                            "latitude": 29.56,
                            "longitude": 106.55,
                            "timezone": "Asia/Shanghai",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-08-14T16:00",
                    "temperature_2m": 34.2,
                    "apparent_temperature": 37.0,
                    "weather_code": 2,
                    "wind_speed_10m": 8.1,
                },
                "current_units": {
                    "temperature_2m": "°C",
                    "apparent_temperature": "°C",
                    "wind_speed_10m": "km/h",
                },
            },
        )

    result = CommonTools(_client(handler)).weather_current("重庆")

    assert result["location"]["name"] == "Chongqing"
    assert result["current"]["temperature"] == 34.2
    assert result["current"]["condition"] == "局部多云"
    assert result["source"] == "Open-Meteo"


def test_exchange_rate_returns_timestamped_quote() -> None:
    client = _client(
        lambda _request: httpx.Response(
            200,
            json={"amount": 1.0, "base": "USD", "date": "2026-08-13", "rates": {"CNY": 7.15}},
        )
    )

    result = CommonTools(client).exchange_rate("usd", "cny", 2)

    assert result["base"] == "USD"
    assert result["quote"] == "CNY"
    assert result["rate"] == 7.15
    assert result["converted_amount"] == 14.3


def test_web_search_normalizes_public_results() -> None:
    client = _client(
        lambda _request: httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "title": "Agent engineering update",
                        "url": "https://example.com/agent",
                        "domain": "example.com",
                        "seendate": "20260814T080000Z",
                        "language": "English",
                    }
                ]
            },
        )
    )

    result = CommonTools(client).web_search("AI Agent", max_results=3)

    assert result["results"][0]["title"] == "Agent engineering update"
    assert result["source"] == "GDELT"


def test_web_fetch_rejects_private_network_urls() -> None:
    tools = CommonTools(_client(lambda _request: httpx.Response(200)))

    with pytest.raises(CommonToolInputError, match="public"):
        tools.web_fetch_summary("http://127.0.0.1/admin")


def test_web_fetch_extracts_bounded_visible_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "retail_analytics_agent.common_tools.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    client = _client(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Example</title><script>ignore()</script></head>"
            "<body><main><h1>Public article</h1><p>Useful content.</p></main></body></html>",
        )
    )

    result = CommonTools(client).web_fetch_summary("https://example.com/article")

    assert result["title"] == "Example"
    assert "Public article Useful content." in result["text"]
    assert "ignore" not in result["text"]
