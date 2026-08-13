from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


class MCPExportError(ValueError):
    pass


DEFAULT_TEMPLATES: dict[str, str] = {
    "operations_review": (
        "# {title}\n\n## 摘要\n{executive_summary}\n\n"
        "## 结论\n{findings}\n\n## 数据证据\n{data_evidence}\n\n"
        "## 文档证据\n{document_evidence}\n\n## 限制\n{limitations}\n"
    ),
}

mcp = FastMCP("operations-report-export")


@mcp.tool()
def read_report_template(template_name: str) -> str:
    """Read one allowlisted operations report template."""
    try:
        return DEFAULT_TEMPLATES[template_name]
    except KeyError as exc:
        raise MCPExportError("template is not allowlisted") from exc


@mcp.tool()
def export_operations_report(
    report: dict[str, Any],
    format: str = "markdown",
) -> str:
    """Render a validated operations report as Markdown."""
    if format != "markdown":
        raise MCPExportError("only markdown export is enabled")
    title = str(report.get("title", "经营分析报告"))
    findings = "\n".join(
        f"- {item.get('statement', '')}"
        for item in report.get("findings", [])
    )
    return read_report_template("operations_review").format(
        title=title,
        executive_summary=report.get("executive_summary", ""),
        findings=findings,
        data_evidence="、".join(report.get("data_evidence", [])) or "无",
        document_evidence="、".join(report.get("document_evidence", [])) or "无",
        limitations="、".join(report.get("limitations", [])) or "无",
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
