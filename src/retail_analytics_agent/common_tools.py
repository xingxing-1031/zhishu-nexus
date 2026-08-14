from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


class CommonToolError(RuntimeError):
    """Stable error for an unavailable or invalid public tool request."""


class CommonToolInputError(CommonToolError, ValueError):
    """Raised when a common tool request is outside its safe input boundary."""


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self._in_title = True
        if normalized in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self._in_title = False
        if normalized in {"script", "style", "noscript", "template"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._ignored_depth == 0 and data.strip():
            self._parts.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _weather_condition(code: int) -> str:
    return {
        0: "晴",
        1: "大部晴朗",
        2: "局部多云",
        3: "阴",
        45: "雾",
        48: "冻雾",
        51: "小毛毛雨",
        53: "毛毛雨",
        55: "大毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "阵雨",
        81: "中阵雨",
        82: "强阵雨",
        95: "雷雨",
        96: "雷雨伴冰雹",
        99: "强雷雨伴冰雹",
    }.get(code, "未知天气")


def _assert_public_host(host: str) -> None:
    if not host:
        raise CommonToolInputError("URL must contain a public host")
    normalized = host.rstrip(".").casefold()
    if normalized in {"localhost", "localhost.localdomain"}:
        raise CommonToolInputError("URL must target a public host")
    try:
        addresses = [ipaddress.ip_address(normalized)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(normalized, None)
            ]
        except (OSError, ValueError) as exc:
            raise CommonToolInputError("URL host could not be resolved safely") from exc
    if any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise CommonToolInputError("URL must target a public host")


@dataclass
class CommonTools:
    client: httpx.Client
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    timeout_seconds: float = 10
    max_response_bytes: int = 1_000_000

    def _json(self, url: str, *, params: dict[str, object]) -> dict:
        try:
            response = self.client.get(
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            if len(response.content) > self.max_response_bytes:
                raise CommonToolError("external response exceeded size limit")
            payload = response.json()
        except CommonToolError:
            raise
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise CommonToolError("external service is unavailable") from exc
        if not isinstance(payload, dict):
            raise CommonToolError("external service returned an invalid object")
        return payload

    def time_now(self, timezone: str = "Asia/Shanghai") -> dict[str, object]:
        try:
            target_zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise CommonToolInputError("unknown IANA timezone") from exc
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        local = current.astimezone(target_zone)
        return {
            "timezone": timezone,
            "local_time": local.isoformat(),
            "weekday": local.strftime("%A"),
            "source": "system_clock",
        }

    def weather_current(self, city: str) -> dict[str, object]:
        if not city.strip() or len(city) > 80:
            raise CommonToolInputError("city is required and must be short")
        location = self._json(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city.strip(), "count": 1, "language": "zh", "format": "json"},
        )
        matches = location.get("results")
        if not isinstance(matches, list) or not matches:
            raise CommonToolError("city was not found")
        place = matches[0]
        forecast = self._json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": (
                    "temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
            },
        )
        current = forecast.get("current")
        units = forecast.get("current_units", {})
        if not isinstance(current, dict):
            raise CommonToolError("weather service returned no current observation")
        return {
            "location": {
                "name": place.get("name", city.strip()),
                "country": place.get("country", ""),
                "latitude": place.get("latitude"),
                "longitude": place.get("longitude"),
                "timezone": place.get("timezone"),
            },
            "current": {
                "observed_at": current.get("time"),
                "temperature": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "condition": _weather_condition(int(current.get("weather_code", -1))),
                "wind_speed": current.get("wind_speed_10m"),
                "units": units,
            },
            "source": "Open-Meteo",
        }

    def exchange_rate(
        self,
        base: str,
        quote: str,
        amount: float = 1,
    ) -> dict[str, object]:
        base_code = base.strip().upper()
        quote_code = quote.strip().upper()
        if len(base_code) != 3 or len(quote_code) != 3:
            raise CommonToolInputError("currency codes must be ISO 4217 values")
        if amount <= 0 or amount > 1_000_000_000:
            raise CommonToolInputError("amount must be between 0 and 1 billion")
        payload = self._json(
            "https://api.frankfurter.app/latest",
            params={"from": base_code, "to": quote_code},
        )
        rates = payload.get("rates")
        if not isinstance(rates, dict) or quote_code not in rates:
            raise CommonToolError("exchange service returned no requested quote")
        rate = float(rates[quote_code])
        return {
            "base": base_code,
            "quote": quote_code,
            "rate": rate,
            "amount": amount,
            "converted_amount": round(amount * rate, 8),
            "date": payload.get("date"),
            "source": "Frankfurter",
        }

    def web_search(self, query: str, max_results: int = 5) -> dict[str, object]:
        if not query.strip() or len(query) > 500:
            raise CommonToolInputError("search query is required and must be short")
        if max_results < 1 or max_results > 10:
            raise CommonToolInputError("max_results must be between 1 and 10")
        payload = self._json(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query.strip(),
                "mode": "artlist",
                "format": "json",
                "sort": "hybridrel",
                "maxrecords": max_results,
            },
        )
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise CommonToolError("search service returned invalid articles")
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "domain": item.get("domain", ""),
                "published_at": item.get("seendate"),
                "language": item.get("language"),
            }
            for item in articles[:max_results]
            if isinstance(item, dict) and item.get("url")
        ]
        return {"query": query.strip(), "results": results, "source": "GDELT"}

    def web_fetch_summary(self, url: str) -> dict[str, object]:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            raise CommonToolInputError("URL must use http or https")
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            raise CommonToolInputError("URL credentials and custom ports are not allowed")
        _assert_public_host(parsed.hostname or "")
        try:
            response = self.client.get(
                url,
                follow_redirects=False,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "ZhishuNexus/1.0"},
            )
            response.raise_for_status()
            if len(response.content) > self.max_response_bytes:
                raise CommonToolError("web page exceeded size limit")
        except CommonToolError:
            raise
        except httpx.HTTPError as exc:
            raise CommonToolError("web page is unavailable") from exc
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "text/" not in content_type:
            raise CommonToolInputError("URL does not contain readable text")
        parser = _VisibleTextParser()
        parser.feed(response.text)
        text = parser.text[:12_000]
        if not text:
            raise CommonToolError("web page contained no readable text")
        return {
            "url": url,
            "title": parser.title.strip()[:500],
            "text": text,
            "truncated": len(parser.text) > len(text),
            "source": "public_web",
        }
