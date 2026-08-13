from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpToolClient:
    command: str
    args: tuple[str, ...]
    timeout_seconds: float = 10

    def discover(self) -> tuple[str, ...]:
        return asyncio.run(self._request("discover", "", {}))

    def call(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = asyncio.run(self._request("call", tool_name, payload))
        if not isinstance(result, dict):
            raise McpClientError("MCP tool returned a non-object result")
        return result

    async def _request(
        self,
        action: str,
        tool_name: str,
        payload: dict[str, Any],
    ):
        parameters = StdioServerParameters(
            command=self.command,
            args=list(self.args),
        )
        error: McpClientError | None = None
        value: object = ()
        try:
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    discovered = await asyncio.wait_for(
                        session.list_tools(),
                        timeout=self.timeout_seconds,
                    )
                    names = tuple(tool.name for tool in discovered.tools)
                    if action == "discover":
                        value = names
                    elif tool_name not in names:
                        error = McpClientError(
                            f"tool is not discovered: {tool_name}"
                        )
                    else:
                        result = await asyncio.wait_for(
                            session.call_tool(tool_name, payload),
                            timeout=self.timeout_seconds,
                        )
                        if result.isError:
                            message = " ".join(
                                getattr(item, "text", "")
                                for item in result.content
                            ).strip()
                            error = McpClientError(message or "MCP tool failed")
                        elif isinstance(result.structuredContent, dict):
                            value = result.structuredContent
                        else:
                            text = "\n".join(
                                getattr(item, "text", "")
                                for item in result.content
                            )
                            try:
                                value = json.loads(text)
                            except json.JSONDecodeError:
                                value = {"content": text}
        except Exception as exc:
            raise McpClientError("MCP server unavailable") from exc
        if error is not None:
            raise error
        return value
