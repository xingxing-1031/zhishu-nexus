from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class MCPExportError(ValueError):
    pass


DEFAULT_TEMPLATES: dict[str, str] = {
    "operations_review": "# {title}\n\n## 摘要\n{executive_summary}\n\n## 结论\n{findings}\n\n## 数据证据\n{data_evidence}\n\n## 文档证据\n{document_evidence}\n\n## 限制\n{limitations}\n",
}


def read_report_template(template_name: str) -> str:
    try:
        return DEFAULT_TEMPLATES[template_name]
    except KeyError as exc:
        raise MCPExportError("template is not allowlisted") from exc


def export_operations_report(report: dict[str, Any], format: str = "markdown") -> str:
    if format != "markdown":
        raise MCPExportError("only markdown export is enabled")
    title = str(report.get("title", "经营分析报告"))
    findings = "\n".join(
        f"- {item.get('statement', '')}"
        for item in report.get("findings", [])
    )
    template = read_report_template("operations_review")
    return template.format(
        title=title,
        executive_summary=report.get("executive_summary", ""),
        findings=findings,
        data_evidence="、".join(report.get("data_evidence", [])) or "无",
        document_evidence="、".join(report.get("document_evidence", [])) or "无",
        limitations="、".join(report.get("limitations", [])) or "无",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed operations report MCP tool server")
    parser.add_argument("--stdio", action="store_true", help="serve JSONL tool calls over stdin/stdout")
    args = parser.parse_args()
    if not args.stdio:
        parser.error("--stdio is required")
    import sys

    for line in sys.stdin:
        try:
            request = json.loads(line)
            name = request.get("name")
            if name == "read_report_template":
                result = {"template": read_report_template(request.get("template_name", ""))}
            elif name == "export_operations_report":
                result = {"markdown": export_operations_report(request.get("report", {}), request.get("format", "markdown"))}
            else:
                raise MCPExportError("unknown MCP tool")
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False), flush=True)
        except (json.JSONDecodeError, MCPExportError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
