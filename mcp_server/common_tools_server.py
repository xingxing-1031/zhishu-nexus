from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from retail_analytics_agent.common_tools import CommonTools  # noqa: E402

_client = httpx.Client()
_tools = CommonTools(
    _client,
    timeout_seconds=float(os.getenv("MCP_HTTP_TIMEOUT_SECONDS", "10")),
    max_response_bytes=int(os.getenv("MCP_MAX_RESPONSE_BYTES", "1000000")),
)
mcp = FastMCP("zhishu-common-tools")


@mcp.tool()
def time_now(timezone: str = "Asia/Shanghai") -> dict[str, object]:
    """Return the current time for an IANA timezone."""
    return _tools.time_now(timezone)


@mcp.tool()
def weather_current(city: str) -> dict[str, object]:
    """Return current weather for a public city name."""
    return _tools.weather_current(city)


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> dict[str, object]:
    """Search recent public news and web articles."""
    return _tools.web_search(query, max_results)


@mcp.tool()
def web_fetch_summary(url: str) -> dict[str, object]:
    """Fetch bounded visible text from a public web page."""
    return _tools.web_fetch_summary(url)


@mcp.tool()
def exchange_rate(base: str, quote: str, amount: float = 1) -> dict[str, object]:
    """Return a public exchange-rate quote."""
    return _tools.exchange_rate(base, quote, amount)


if __name__ == "__main__":
    mcp.run(transport="stdio")
