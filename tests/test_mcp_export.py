import sys

import pytest

from retail_analytics_agent.mcp_client import McpClientError, McpToolClient


def _client() -> McpToolClient:
    return McpToolClient((sys.executable, "mcp_server/operations_export_server.py"))


def test_mcp_client_discovers_and_calls_export_tool() -> None:
    client = _client()
    assert "export_operations_report" in client.discover()
    result = client.call("export_operations_report", {"report": {
        "title": "退款复盘", "executive_summary": "摘要",
        "findings": [{"statement": "退款率上升"}],
        "data_evidence": ["query:1"], "document_evidence": ["policy:1"],
    }})
    assert "退款率上升" in result["markdown"]
    assert "query:1" in result["markdown"]


def test_mcp_client_rejects_unknown_tool() -> None:
    with pytest.raises(McpClientError, match="not discovered"):
        _client().call("delete_everything", {})


def test_mcp_client_rejects_unsupported_format() -> None:
    with pytest.raises(McpClientError, match="only markdown"):
        _client().call("export_operations_report", {"report": {}, "format": "pdf"})
