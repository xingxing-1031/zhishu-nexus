from collections.abc import Callable, Iterator
from dataclasses import dataclass
from operator import add
from typing import Annotated, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from retail_analytics_agent.approval import (
    ApprovalAuditRecord,
    ApprovalAuditSink,
    ApprovalAuditStatus,
    TrustedApprovalResolution,
    approval_status_for_risk,
    assess_query_risk,
)
from retail_analytics_agent.charting import build_chart_spec
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    ApprovalDecision,
    ApprovalStatus,
    AnalysisPlan,
    AnalysisRequest,
    ChartSpec,
    RetrievalEvidence,
    QueryRisk,
)
from retail_analytics_agent.model_adapters import (
    AnalysisPlanner,
    ResultSummarizer,
    SQLGenerator,
)
from retail_analytics_agent.sql_safety import PreparedSQL
from retail_analytics_agent.workflow_tools import (
    RetrievalTool,
    SQLExecutionTool,
    SQLExecutionToolError,
    SQLValidationTool,
    SQLValidationToolError,
)


class AnalysisState(TypedDict):
    request_id: str
    user_id: str
    access_role: AccessRole
    question: str
    max_rows: int
    plan: AnalysisPlan | None
    retrieved_context: list[RetrievalEvidence]
    generated_sql: str | None
    prepared_sql: PreparedSQL | None
    sql_valid: bool | None
    sql_validation_error: str | None
    query_risk: QueryRisk | None
    approval_status: ApprovalStatus
    reviewed_by: str | None
    approval_reason: str | None
    query_rows: list[dict[str, object]]
    execution_error: str | None
    final_answer: str | None
    chart_spec: ChartSpec | None
    retry_count: int
    max_retries: int
    trace: Annotated[list[str], add]


AnalysisStateUpdate = dict[str, object]
AnalysisNode = Callable[[AnalysisState], AnalysisStateUpdate]


class CompiledAnalysisGraph(Protocol):
    def invoke(
        self,
        state: AnalysisState | Command | None,
        config: RunnableConfig | None = None,
    ) -> AnalysisState: ...

    def stream(
        self,
        state: AnalysisState,
        config: RunnableConfig | None = None,
        *,
        stream_mode: str,
    ) -> Iterator[AnalysisState]: ...

    def get_state(self, config: RunnableConfig): ...


@dataclass(frozen=True, slots=True)
class WorkflowNodes:
    plan: AnalysisNode
    retrieve: AnalysisNode
    generate_sql: AnalysisNode
    validate_sql: AnalysisNode
    assess_risk: AnalysisNode
    request_approval: AnalysisNode
    execute_sql: AnalysisNode
    summarize: AnalysisNode
    fail: AnalysisNode


PLAN_NODE = "plan"
RETRIEVE_NODE = "retrieve"
GENERATE_SQL_NODE = "generate_sql"
VALIDATE_SQL_NODE = "validate_sql"
ASSESS_RISK_NODE = "assess_risk"
REQUEST_APPROVAL_NODE = "request_approval"
EXECUTE_SQL_NODE = "execute_sql"
SUMMARIZE_NODE = "summarize"
FAIL_NODE = "fail"


def create_initial_state(
    request: AnalysisRequest,
    *,
    max_retries: int = 2,
    access_context: AccessContext | None = None,
) -> AnalysisState:
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    active_access = access_context or AccessContext(
        user_id=request.user_id,
        role=AccessRole.ANALYST,
    )
    return AnalysisState(
        request_id=request.request_id,
        user_id=active_access.user_id,
        access_role=active_access.role,
        question=request.question,
        max_rows=request.max_rows,
        plan=None,
        retrieved_context=[],
        generated_sql=None,
        prepared_sql=None,
        sql_valid=None,
        sql_validation_error=None,
        query_risk=None,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        reviewed_by=None,
        approval_reason=None,
        query_rows=[],
        execution_error=None,
        final_answer=None,
        chart_spec=None,
        retry_count=0,
        max_retries=max_retries,
        trace=[],
    )


def create_thread_config(thread_id: str) -> RunnableConfig:
    if not thread_id.strip():
        raise ValueError("thread_id must not be empty")

    return {"configurable": {"thread_id": thread_id}}


def create_plan_node(model: AnalysisPlanner) -> AnalysisNode:
    def plan(state: AnalysisState) -> AnalysisStateUpdate:
        analysis_plan = model.plan(
            state["question"],
            max_rows=state["max_rows"],
        )
        if analysis_plan.limit > state["max_rows"]:
            raise ValueError("analysis plan limit must not exceed max_rows")
        return {
            "plan": analysis_plan,
            "trace": [PLAN_NODE],
        }

    return plan


def create_retrieve_node(tool: RetrievalTool) -> AnalysisNode:
    def retrieve(state: AnalysisState) -> AnalysisStateUpdate:
        plan = state["plan"]
        if plan is None:
            raise ValueError("analysis plan is required before retrieval")

        return {
            "retrieved_context": tool.retrieve(plan),
            "trace": [RETRIEVE_NODE],
        }

    return retrieve


def create_sql_generation_node(model: SQLGenerator) -> AnalysisNode:
    def generate_sql(state: AnalysisState) -> AnalysisStateUpdate:
        plan = state["plan"]
        if plan is None:
            raise ValueError("analysis plan is required before SQL generation")
        evidence = state["retrieved_context"]
        if not evidence:
            raise ValueError("retrieval evidence is required before SQL generation")

        return {
            "generated_sql": model.generate(
                question=state["question"],
                plan=plan,
                evidence=evidence,
                access_role=state["access_role"],
                validation_error=state["sql_validation_error"],
            ),
            "prepared_sql": None,
            "sql_valid": None,
            "query_risk": None,
            "approval_status": ApprovalStatus.NOT_REQUIRED,
            "reviewed_by": None,
            "approval_reason": None,
            "trace": [GENERATE_SQL_NODE],
        }

    return generate_sql


def create_sql_validation_node(tool: SQLValidationTool) -> AnalysisNode:
    def validate_sql(state: AnalysisState) -> AnalysisStateUpdate:
        sql = state["generated_sql"]
        if sql is None:
            return {
                "prepared_sql": None,
                "sql_valid": False,
                "sql_validation_error": "generated SQL is required",
                "retry_count": state["retry_count"] + 1,
                "trace": [VALIDATE_SQL_NODE],
            }

        try:
            prepared_sql = tool.validate(
                request_id=state["request_id"],
                user_id=state["user_id"],
                sql=sql,
                max_rows=state["max_rows"],
                access_role=state["access_role"],
            )
        except SQLValidationToolError as exc:
            return {
                "prepared_sql": None,
                "sql_valid": False,
                "sql_validation_error": str(exc),
                "retry_count": state["retry_count"] + 1,
                "trace": [VALIDATE_SQL_NODE],
            }

        return {
            "prepared_sql": prepared_sql,
            "sql_valid": True,
            "sql_validation_error": None,
            "trace": [VALIDATE_SQL_NODE],
        }

    return validate_sql


def create_query_risk_node(
    audit_sink: ApprovalAuditSink,
) -> AnalysisNode:
    def assess_risk(state: AnalysisState) -> AnalysisStateUpdate:
        prepared_sql = state["prepared_sql"]
        if prepared_sql is None:
            raise ValueError("validated SQL is required before risk assessment")

        risk = assess_query_risk(prepared_sql)
        status = approval_status_for_risk(risk)
        if status is ApprovalStatus.PENDING:
            audit_sink.record(
                ApprovalAuditRecord(
                    request_id=state["request_id"],
                    requester_id=state["user_id"],
                    access_role=state["access_role"],
                    sql=prepared_sql.sql,
                    status=ApprovalAuditStatus.PENDING,
                    reasons=risk.reasons,
                )
            )
        return {
            "query_risk": risk,
            "approval_status": status,
            "trace": [ASSESS_RISK_NODE],
        }

    return assess_risk


def create_approval_node(
    audit_sink: ApprovalAuditSink,
) -> AnalysisNode:
    def request_approval(state: AnalysisState) -> AnalysisStateUpdate:
        prepared_sql = state["prepared_sql"]
        risk = state["query_risk"]
        if prepared_sql is None or risk is None or not risk.requires_approval:
            raise ValueError("approval is only valid for a high-risk query")

        raw_resolution = interrupt(
            {
                "request_id": state["request_id"],
                "sql": prepared_sql.sql,
                "reasons": list(risk.reasons),
                "sensitive_columns": list(risk.sensitive_columns),
                "result_limit": risk.result_limit,
            }
        )
        resolution = TrustedApprovalResolution.model_validate(raw_resolution)
        decision = resolution.decision
        reason = resolution.reason.strip() if resolution.reason else None
        if resolution.reviewer_role is not AccessRole.ADMIN:
            decision = ApprovalDecision.REJECT
            reason = "approval requires an admin reviewer"

        status = (
            ApprovalStatus.APPROVED
            if decision is ApprovalDecision.APPROVE
            else ApprovalStatus.REJECTED
        )
        audit_sink.record(
            ApprovalAuditRecord(
                request_id=state["request_id"],
                requester_id=state["user_id"],
                access_role=state["access_role"],
                sql=prepared_sql.sql,
                status=(
                    ApprovalAuditStatus.APPROVED
                    if status is ApprovalStatus.APPROVED
                    else ApprovalAuditStatus.REJECTED
                ),
                reasons=risk.reasons,
                reviewer_id=resolution.reviewer_id,
                decision_reason=reason,
            )
        )
        return {
            "approval_status": status,
            "reviewed_by": resolution.reviewer_id,
            "approval_reason": reason,
            "trace": [REQUEST_APPROVAL_NODE],
        }

    return request_approval


def create_sql_execution_node(tool: SQLExecutionTool) -> AnalysisNode:
    def execute_sql(state: AnalysisState) -> AnalysisStateUpdate:
        original_sql = state["generated_sql"]
        prepared_sql = state["prepared_sql"]
        if original_sql is None or prepared_sql is None:
            return {
                "query_rows": [],
                "execution_error": "validated SQL is required",
                "trace": [EXECUTE_SQL_NODE],
            }

        try:
            result = tool.execute(
                request_id=state["request_id"],
                user_id=state["user_id"],
                original_sql=original_sql,
                prepared_sql=prepared_sql,
            )
        except SQLExecutionToolError as exc:
            return {
                "query_rows": [],
                "execution_error": str(exc),
                "trace": [EXECUTE_SQL_NODE],
            }

        return {
            "query_rows": result.rows,
            "execution_error": None,
            "trace": [EXECUTE_SQL_NODE],
        }

    return execute_sql


def create_summarize_node(model: ResultSummarizer) -> AnalysisNode:
    def summarize(state: AnalysisState) -> AnalysisStateUpdate:
        plan = state["plan"]
        if plan is None:
            raise ValueError("analysis plan is required before summarization")
        if state["execution_error"] is not None:
            raise ValueError("successful query execution is required before summarization")

        return {
            "final_answer": model.summarize(
                question=state["question"],
                plan=plan,
                rows=state["query_rows"],
            ),
            "chart_spec": build_chart_spec(plan, state["query_rows"]),
            "trace": [SUMMARIZE_NODE],
        }

    return summarize


def create_fail_node() -> AnalysisNode:
    def fail(state: AnalysisState) -> AnalysisStateUpdate:
        reason = (
            state["execution_error"]
            or state["approval_reason"]
            or state["sql_validation_error"]
            or "unknown workflow error"
        )
        return {
            "final_answer": f"分析失败：{reason}",
            "trace": [FAIL_NODE],
        }

    return fail


def create_workflow_nodes(
    *,
    planner: AnalysisPlanner,
    retrieval_tool: RetrievalTool,
    sql_generator: SQLGenerator,
    validation_tool: SQLValidationTool,
    approval_audit_sink: ApprovalAuditSink,
    execution_tool: SQLExecutionTool,
    summarizer: ResultSummarizer,
) -> WorkflowNodes:
    return WorkflowNodes(
        plan=create_plan_node(planner),
        retrieve=create_retrieve_node(retrieval_tool),
        generate_sql=create_sql_generation_node(sql_generator),
        validate_sql=create_sql_validation_node(validation_tool),
        assess_risk=create_query_risk_node(approval_audit_sink),
        request_approval=create_approval_node(approval_audit_sink),
        execute_sql=create_sql_execution_node(execution_tool),
        summarize=create_summarize_node(summarizer),
        fail=create_fail_node(),
    )


def route_after_sql_validation(state: AnalysisState) -> str:
    if state["sql_valid"] is True:
        return ASSESS_RISK_NODE
    if state["retry_count"] <= state["max_retries"]:
        return GENERATE_SQL_NODE
    return FAIL_NODE


def route_after_risk_assessment(state: AnalysisState) -> str:
    if state["approval_status"] is ApprovalStatus.PENDING:
        return REQUEST_APPROVAL_NODE
    return EXECUTE_SQL_NODE


def route_after_approval(state: AnalysisState) -> str:
    if state["approval_status"] is ApprovalStatus.APPROVED:
        return EXECUTE_SQL_NODE
    return FAIL_NODE


def route_after_sql_execution(state: AnalysisState) -> str:
    if state["execution_error"] is not None:
        return FAIL_NODE
    return SUMMARIZE_NODE


def build_analysis_graph(
    nodes: WorkflowNodes,
    *,
    checkpointer: BaseCheckpointSaver[object] | None = None,
    interrupt_before: list[str] | None = None,
) -> CompiledAnalysisGraph:
    graph = StateGraph(AnalysisState)

    graph.add_node(PLAN_NODE, nodes.plan)
    graph.add_node(RETRIEVE_NODE, nodes.retrieve)
    graph.add_node(GENERATE_SQL_NODE, nodes.generate_sql)
    graph.add_node(VALIDATE_SQL_NODE, nodes.validate_sql)
    graph.add_node(ASSESS_RISK_NODE, nodes.assess_risk)
    graph.add_node(REQUEST_APPROVAL_NODE, nodes.request_approval)
    graph.add_node(EXECUTE_SQL_NODE, nodes.execute_sql)
    graph.add_node(SUMMARIZE_NODE, nodes.summarize)
    graph.add_node(FAIL_NODE, nodes.fail)

    graph.add_edge(START, PLAN_NODE)
    graph.add_edge(PLAN_NODE, RETRIEVE_NODE)
    graph.add_edge(RETRIEVE_NODE, GENERATE_SQL_NODE)
    graph.add_edge(GENERATE_SQL_NODE, VALIDATE_SQL_NODE)
    graph.add_conditional_edges(
        VALIDATE_SQL_NODE,
        route_after_sql_validation,
        {
            ASSESS_RISK_NODE: ASSESS_RISK_NODE,
            GENERATE_SQL_NODE: GENERATE_SQL_NODE,
            FAIL_NODE: FAIL_NODE,
        },
    )
    graph.add_conditional_edges(
        ASSESS_RISK_NODE,
        route_after_risk_assessment,
        {
            REQUEST_APPROVAL_NODE: REQUEST_APPROVAL_NODE,
            EXECUTE_SQL_NODE: EXECUTE_SQL_NODE,
        },
    )
    graph.add_conditional_edges(
        REQUEST_APPROVAL_NODE,
        route_after_approval,
        {
            EXECUTE_SQL_NODE: EXECUTE_SQL_NODE,
            FAIL_NODE: FAIL_NODE,
        },
    )
    graph.add_conditional_edges(
        EXECUTE_SQL_NODE,
        route_after_sql_execution,
        {
            SUMMARIZE_NODE: SUMMARIZE_NODE,
            FAIL_NODE: FAIL_NODE,
        },
    )
    graph.add_edge(SUMMARIZE_NODE, END)
    graph.add_edge(FAIL_NODE, END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
    )
