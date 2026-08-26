from __future__ import annotations

from pydantic import Field

from retail_analytics_agent.agent_models import ToolResult, ToolRisk
from retail_analytics_agent.analysis_service import AnalysisRunner
from retail_analytics_agent.knowledge_adapter import (
    KnowledgeAdapterError,
    KnowledgeQuery,
    KnowledgeRetriever,
)
from retail_analytics_agent.mcp_client import McpClientError, McpToolClient
from retail_analytics_agent.models import (
    AccessContext,
    AnalysisRequest,
    AnalysisResponse,
)
from retail_analytics_agent.tool_registry import ToolInput, ToolRegistry, ToolSpec


class SQLAnalysisInput(ToolInput):
    request_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    max_rows: int = Field(ge=1, le=1000)
    dataset_id: str | None = Field(default=None, max_length=80)
    dataset_version: int | None = Field(default=None, ge=1)


class KnowledgeSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=40)
    departments: tuple[str, ...] = Field(default=(), max_length=20)
    top_k: int = Field(default=5, ge=1, le=20)


class ReportExportInput(ToolInput):
    report: dict[str, object]
    format: str = Field(default="markdown", pattern="^markdown$")


def create_agent_tool_registry(
    analysis_runner: AnalysisRunner,
    knowledge: KnowledgeRetriever | None,
    mcp_client: McpToolClient | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()

    def run_sql(payload, access_context: AccessContext) -> ToolResult:
        outcome = analysis_runner.run(
            AnalysisRequest(
                request_id=payload.request_id,
                user_id=payload.user_id,
                question=payload.question,
                max_rows=payload.max_rows,
                dataset_id=payload.dataset_id,
                dataset_version=payload.dataset_version,
            ),
            access_context,
        )
        evidence_ids: tuple[str, ...] = ()
        if isinstance(outcome, AnalysisResponse):
            evidence_ids = (
                f"query:{payload.request_id}",
                *outcome.evidence_source_ids,
            )
        return ToolResult(
            tool_name="sql.query",
            status=("succeeded" if isinstance(outcome, AnalysisResponse) else "stopped"),
            payload={
                "outcome": outcome.model_dump(
                    mode="json",
                    exclude_computed_fields=True,
                )
            },
            evidence_ids=evidence_ids,
        )

    registry.register(
        ToolSpec(
            name="sql.query",
            description="Run the existing auditable Text-to-SQL workflow.",
            input_model=SQLAnalysisInput,
            risk=ToolRisk.HIGH,
            timeout_seconds=180,
        ),
        run_sql,
    )

    if knowledge is not None:
        def search_knowledge(payload, access_context: AccessContext) -> ToolResult:
            if payload.user_id != access_context.user_id:
                raise PermissionError("knowledge request belongs to another user")
            try:
                items = knowledge.retrieve(KnowledgeQuery(
                    query=payload.query,
                    user_id=payload.user_id,
                    role=payload.role,
                    departments=payload.departments,
                    top_k=payload.top_k,
                ))
            except KnowledgeAdapterError as exc:
                raise RuntimeError("knowledge service unavailable") from exc
            return ToolResult(
                tool_name="knowledge.search",
                status="succeeded",
                payload={"evidence": [item.model_dump(mode="json") for item in items]},
                evidence_ids=tuple(item.source_id for item in items),
            )

        registry.register(
            ToolSpec(
                name="knowledge.search",
                description="Retrieve permission-filtered enterprise evidence.",
                input_model=KnowledgeSearchInput,
                risk=ToolRisk.MEDIUM,
                timeout_seconds=30,
            ),
            search_knowledge,
        )
    if mcp_client is not None:
        try:
            discovered = set(mcp_client.discover())
        except McpClientError:
            # Export is optional: core SQL/RAG analysis must remain available
            # when the separately managed MCP process is down.
            discovered = set()
        if "export_operations_report" not in discovered:
            return registry

        def export_report(payload, access_context: AccessContext) -> ToolResult:
            del access_context
            result = mcp_client.call(
                "export_operations_report",
                {
                    "report": payload.report,
                    "format": payload.format,
                },
            )
            content = result.get("result", result.get("content", ""))
            return ToolResult(
                tool_name="report.export",
                status="succeeded",
                payload={"markdown": str(content)},
            )

        registry.register(
            ToolSpec(
                name="report.export",
                description="Export an operations report through MCP.",
                input_model=ReportExportInput,
                risk=ToolRisk.LOW,
                timeout_seconds=15,
            ),
            export_report,
        )
    return registry
