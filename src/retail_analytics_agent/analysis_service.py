from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.model_adapters import (
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStreamEvent,
)
from retail_analytics_agent.settings import get_settings
from retail_analytics_agent.workflow import (
    CompiledAnalysisGraph,
    build_analysis_graph,
    create_initial_state,
    create_workflow_nodes,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    SafeSQLExecutionTool,
    SQLGlotValidationTool,
)


class AnalysisRunError(RuntimeError):
    """Stable error for a workflow that cannot produce a successful response."""


class AnalysisRunner(Protocol):
    def run(self, request: AnalysisRequest) -> AnalysisResponse: ...

    def stream(
        self,
        request: AnalysisRequest,
    ) -> Iterator[AnalysisStreamEvent]: ...


_NODE_STATUS_MESSAGES = {
    "plan": "分析问题已转换为结构化计划",
    "retrieve": "指标口径和数据结构检索完成",
    "generate_sql": "查询语句生成完成",
    "validate_sql": "SQL 安全校验完成",
    "execute_sql": "零售数据库查询完成",
    "summarize": "分析结论和图表规格生成完成",
    "fail": "分析流程执行失败",
}


@dataclass(frozen=True, slots=True)
class LangGraphAnalysisRunner:
    graph: CompiledAnalysisGraph

    def run(self, request: AnalysisRequest) -> AnalysisResponse:
        result = self.graph.invoke(create_initial_state(request))
        return self._to_response(result)

    def stream(
        self,
        request: AnalysisRequest,
    ) -> Iterator[AnalysisStreamEvent]:
        yield AnalysisStreamEvent(
            event="status",
            node=None,
            message="分析请求已接收",
        )
        last_node: str | None = None
        final_state = None
        for state in self.graph.stream(
            create_initial_state(request),
            stream_mode="values",
        ):
            final_state = state
            current_node = state["trace"][-1] if state["trace"] else None
            if current_node is None or current_node == last_node:
                continue
            last_node = current_node
            yield AnalysisStreamEvent(
                event="status",
                node=current_node,
                message=_NODE_STATUS_MESSAGES.get(
                    current_node,
                    "正在处理分析请求",
                ),
            )

        if final_state is None:
            raise AnalysisRunError("analysis workflow returned no state")
        response = self._to_response(final_state)
        yield AnalysisStreamEvent(
            event="result",
            node=None,
            message="分析完成",
            response=response,
        )

    @staticmethod
    def _to_response(result) -> AnalysisResponse:
        if result["execution_error"] is not None:
            raise AnalysisRunError(result["execution_error"])
        if result["sql_valid"] is not True:
            raise AnalysisRunError(
                result["sql_validation_error"] or "SQL validation failed"
            )
        plan = result["plan"]
        answer = result["final_answer"]
        if plan is None or answer is None:
            raise AnalysisRunError("analysis workflow returned an incomplete result")

        return AnalysisResponse(
            request_id=result["request_id"],
            answer=answer,
            plan=plan,
            rows=result["query_rows"],
            chart_spec=result["chart_spec"],
            evidence_source_ids=tuple(
                item.source_id for item in result["retrieved_context"]
            ),
            retry_count=result["retry_count"],
            trace=tuple(result["trace"]),
        )


def get_analysis_runner() -> Iterator[AnalysisRunner]:
    settings = get_settings()
    audit_sink = DatabaseAuditSink()
    with (
        httpx.Client(
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
        ) as model_client,
        connect_to_database(settings) as query_connection,
    ):
        nodes = create_workflow_nodes(
            planner=OllamaAnalysisPlanner(
                model_client,
                model=settings.ollama_model,
            ),
            retrieval_tool=CatalogRetrievalTool(),
            sql_generator=OllamaSQLGenerator(
                model_client,
                model=settings.ollama_model,
            ),
            validation_tool=SQLGlotValidationTool(audit_sink),
            execution_tool=SafeSQLExecutionTool(
                query_connection,
                audit_sink,
            ),
            summarizer=OllamaResultSummarizer(
                model_client,
                model=settings.ollama_model,
            ),
        )
        yield LangGraphAnalysisRunner(build_analysis_graph(nodes))
