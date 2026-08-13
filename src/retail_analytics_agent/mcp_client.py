from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


class McpClientError(RuntimeError):
    pass


@dataclass
class McpToolClient:
    command: tuple[str, ...]
    timeout_seconds: float = 10

    def discover(self) -> tuple[str, ...]:
        return ("read_report_template", "export_operations_report")

    def call(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self.discover():
            raise McpClientError(f"tool is not discovered: {tool_name}")
        request = json.dumps({"name": tool_name, **payload}, ensure_ascii=False) + "\n"
        try:
            completed = subprocess.run(
                [*self.command, "--stdio"], input=request, text=True,
                capture_output=True, timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise McpClientError("MCP server unavailable") from exc
        if completed.returncode != 0:
            raise McpClientError("MCP server exited with an error")
        try:
            response = json.loads(completed.stdout.splitlines()[0])
        except (IndexError, json.JSONDecodeError) as exc:
            raise McpClientError("invalid MCP response") from exc
        if not response.get("ok"):
            raise McpClientError(str(response.get("error", "MCP tool failed")))
        return response["result"]
