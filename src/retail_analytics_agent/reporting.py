from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from retail_analytics_agent.agent_models import (
    OperationsReport,
    ReportFinding,
    ToolCallRecord,
    ToolResult,
)


@dataclass(frozen=True)
class ReportComposer:
    def compose(
        self,
        *,
        title: str,
        question: str,
        findings: Sequence[str],
        tool_results: Sequence[ToolResult],
        tool_calls: Sequence[ToolCallRecord] = (),
        limitations: Sequence[str] = (),
    ) -> OperationsReport:
        data_ids = tuple(dict.fromkeys(
            evidence_id
            for result in tool_results
            if result.tool_name == "sql.query"
            for evidence_id in result.evidence_ids
        ))
        document_ids = tuple(dict.fromkeys(
            evidence_id
            for result in tool_results
            if result.tool_name == "knowledge.search"
            for evidence_id in result.evidence_ids
        ))
        finding_items = tuple(
            ReportFinding(
                statement=finding,
                data_evidence_ids=data_ids,
                document_evidence_ids=document_ids,
                confidence="supported" if data_ids or document_ids else "limited",
            )
            for finding in findings
            if finding.strip()
        )
        if not finding_items:
            finding_items = (ReportFinding(
                statement="当前证据不足，系统未生成确定性经营结论。",
                data_evidence_ids=data_ids,
                document_evidence_ids=document_ids,
                confidence="limited",
            ),)
        failed_tools = tuple(
            result.tool_name for result in tool_results if result.status != "succeeded"
        )
        all_limitations = list(limitations)
        if failed_tools:
            all_limitations.append("部分工具未成功执行：" + ", ".join(failed_tools))
        if not data_ids:
            all_limitations.append("没有可引用的结构化数据证据。")
        return OperationsReport(
            title=title,
            executive_summary=(
                f"针对“{question}”完成了 {len(tool_calls)} 次受治理工具调用，"
                f"形成 {len(finding_items)} 条可追溯结论。"
            ),
            findings=finding_items,
            charts=tuple(
                result.payload["chart"]
                for result in tool_results
                if result.tool_name == "chart.build" and "chart" in result.payload
            ),
            data_evidence=data_ids,
            document_evidence=document_ids,
            limitations=tuple(dict.fromkeys(all_limitations)),
        )
