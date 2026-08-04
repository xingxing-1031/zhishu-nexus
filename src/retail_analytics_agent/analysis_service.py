from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import httpx
from langgraph.types import Command

from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.approval import DatabaseApprovalAuditSink
from retail_analytics_agent.checkpointing import open_postgres_checkpointer
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.model_adapters import (
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    ApprovalRejectedResponse,
    ApprovalRequiredResponse,
    ApprovalResolutionRequest,
    ApprovalStatus,
    AnalysisOutcome,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStreamEvent,
)
from retail_analytics_agent.settings import get_settings
from retail_analytics_agent.workflow import (
    CompiledAnalysisGraph,
    build_analysis_graph,
    create_initial_state,
    create_thread_config,
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
    def run(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> AnalysisOutcome: ...

    def stream(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> Iterator[AnalysisStreamEvent]: ...

    def resume_approval(
        self,
        request_id: str,
        resolution: ApprovalResolutionRequest,
        reviewer: AccessContext,
    ) -> AnalysisOutcome: ...

    def get_status(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> AnalysisOutcome: ...


_NODE_STATUS_MESSAGES = {
    "plan": "分析问题已转换为结构化计划",
    "retrieve": "指标口径和数据结构检索完成",
    "generate_sql": "查询语句生成完成",
    "validate_sql": "SQL 安全校验完成",
    "assess_risk": "查询风险评估完成",
    "request_approval": "等待人工审批",
    "execute_sql": "零售数据库查询完成",
    "summarize": "分析结论和图表规格生成完成",
    "fail": "分析流程执行失败",
}


@dataclass(frozen=True, slots=True)
class LangGraphAnalysisRunner:
    graph: CompiledAnalysisGraph

    def run(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> AnalysisOutcome:
        result = self.graph.invoke(
            create_initial_state(request, access_context=access_context),
            create_thread_config(request.request_id),
        )
        return self._to_outcome(result)

    def resume_approval(
        self,
        request_id: str,
        resolution: ApprovalResolutionRequest,
        reviewer: AccessContext,
    ) -> AnalysisOutcome:
        if reviewer.role is not AccessRole.ADMIN:
            raise PermissionError("only an admin can resolve approvals")
        config = create_thread_config(request_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            raise ValueError("approval request was not found")
        if snapshot.values["approval_status"] is not ApprovalStatus.PENDING:
            raise ValueError("approval request is not pending")
        if snapshot.next != ("request_approval",):
            raise ValueError("workflow is not waiting at the approval node")
        result = self.graph.invoke(
            Command(
                resume={
                    "decision": resolution.decision,
                    "reason": resolution.reason,
                    "reviewer_id": reviewer.user_id,
                    "reviewer_role": reviewer.role,
                }
            ),
            config,
        )
        return self._to_outcome(result)

    def get_status(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> AnalysisOutcome:
        snapshot = self.graph.get_state(create_thread_config(request_id))
        if not snapshot.values:
            raise ValueError("analysis request was not found")
        requester_id = snapshot.values["user_id"]
        if (
            viewer.role is not AccessRole.ADMIN
            and viewer.user_id != requester_id
        ):
            raise PermissionError("analysis request belongs to another user")
        return self._to_outcome(snapshot.values)

    def stream(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> Iterator[AnalysisStreamEvent]:
        yield AnalysisStreamEvent(
            event="status",
            node=None,
            message="分析请求已接收",
        )
        last_node: str | None = None
        final_state = None
        for state in self.graph.stream(
            create_initial_state(request, access_context=access_context),
            create_thread_config(request.request_id),
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
        outcome = self._to_outcome(final_state)
        if isinstance(outcome, ApprovalRequiredResponse):
            yield AnalysisStreamEvent(
                event="approval_required",
                node="request_approval",
                message="查询需要人工审批",
                approval=outcome,
            )
            return
        if isinstance(outcome, ApprovalRejectedResponse):
            yield AnalysisStreamEvent(
                event="rejected",
                node="fail",
                message=outcome.reason,
                rejection=outcome,
            )
            return
        yield AnalysisStreamEvent(
            event="result",
            node=None,
            message="分析完成",
            response=outcome,
        )

    @staticmethod
    def _to_outcome(result) -> AnalysisOutcome:
        if result["approval_status"] is ApprovalStatus.PENDING:
            prepared_sql = result["prepared_sql"]
            risk = result["query_risk"]
            if prepared_sql is None or risk is None:
                raise AnalysisRunError("approval state is incomplete")
            return ApprovalRequiredResponse(
                request_id=result["request_id"],
                access_role=result["access_role"],
                sql=prepared_sql.sql,
                reasons=risk.reasons,
                sensitive_columns=risk.sensitive_columns,
                result_limit=risk.result_limit,
                trace=tuple(result["trace"]),
            )
        if result["approval_status"] is ApprovalStatus.REJECTED:
            reviewed_by = result["reviewed_by"]
            if reviewed_by is None:
                raise AnalysisRunError("approval rejection is incomplete")
            return ApprovalRejectedResponse(
                request_id=result["request_id"],
                reviewed_by=reviewed_by,
                reason=result["approval_reason"] or "approval rejected",
                trace=tuple(result["trace"]),
            )
        return LangGraphAnalysisRunner._to_response(result)

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
            access_role=result["access_role"],
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
    approval_audit_sink = DatabaseApprovalAuditSink()
    with (
        httpx.Client(
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
        ) as model_client,
        connect_to_database(settings) as query_connection,
        open_postgres_checkpointer(settings) as checkpointer,
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
            approval_audit_sink=approval_audit_sink,
            execution_tool=SafeSQLExecutionTool(
                query_connection,
                audit_sink,
            ),
            summarizer=OllamaResultSummarizer(
                model_client,
                model=settings.ollama_model,
            ),
        )
        yield LangGraphAnalysisRunner(
            build_analysis_graph(nodes, checkpointer=checkpointer)
        )
