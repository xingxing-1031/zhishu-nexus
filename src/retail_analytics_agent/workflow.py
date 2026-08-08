from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from operator import add
from time import monotonic
from typing import Annotated, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from retail_analytics_agent.access_control import (
    build_sensitive_read_sql,
    requested_sensitive_columns,
    requests_all_columns,
    requests_role_elevation,
    requests_write_operation,
)
from retail_analytics_agent.approval import (
    ApprovalAuditRecord,
    ApprovalAuditSink,
    ApprovalAuditStatus,
    TrustedApprovalResolution,
    approval_status_for_risk,
    assess_query_risk,
)
from retail_analytics_agent.charting import build_chart_spec
from retail_analytics_agent.fault_injection import inject_fault
from retail_analytics_agent.metric_domain import MetricDomainGate
from retail_analytics_agent.model_adapters import (
    AnalysisPlanner,
    ModelInvocationError,
    ResultSummarizer,
    SQLGenerator,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisResultStatus,
    ApprovalDecision,
    ApprovalStatus,
    ChartSpec,
    QueryRisk,
    RetrievalEvidence,
)
from retail_analytics_agent.request_routing import (
    RequestRoute,
    classify_preflight_request,
)
from retail_analytics_agent.sql_safety import PreparedSQL, prepare_safe_sql
from retail_analytics_agent.tracing import (
    TraceStatus,
    record_execution_trace,
)
from retail_analytics_agent.workflow_tools import (
    QueryAwareRetrievalTool,
    RetrievalTool,
    SQLBusinessConsistencyTool,
    SQLBusinessConsistencyToolError,
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
    reference_time: datetime
    request_route: RequestRoute
    request_reason_code: str | None
    assistant_message: str | None
    scope_supported: bool | None
    scope_rejection_reason: str | None
    plan: AnalysisPlan | None
    retrieved_context: list[RetrievalEvidence]
    generated_sql: str | None
    prepared_sql: PreparedSQL | None
    sql_valid: bool | None
    sql_validation_error: str | None
    business_sql_valid: bool | None
    business_sql_validation_error: str | None
    query_risk: QueryRisk | None
    approval_status: ApprovalStatus
    reviewed_by: str | None
    approval_reason: str | None
    query_rows: list[dict[str, object]]
    execution_error: str | None
    final_answer: str | None
    chart_spec: ChartSpec | None
    result_status: AnalysisResultStatus | None
    degradation_reason: str | None
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
    validate_business_sql: AnalysisNode | None = None
    scope: AnalysisNode | None = None
    respond: AnalysisNode | None = None


SCOPE_NODE = "scope"
RESPOND_NODE = "respond"
PLAN_NODE = "plan"
RETRIEVE_NODE = "retrieve"
GENERATE_SQL_NODE = "generate_sql"
VALIDATE_SQL_NODE = "validate_sql"
VALIDATE_BUSINESS_SQL_NODE = "validate_business_sql"
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
    reference_time: datetime | None = None,
) -> AnalysisState:
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    active_access = access_context or AccessContext(
        user_id=request.user_id,
        role=AccessRole.ANALYST,
    )
    active_reference_time = reference_time or datetime.now(timezone.utc)
    if active_reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware")
    return AnalysisState(
        request_id=request.request_id,
        user_id=active_access.user_id,
        access_role=active_access.role,
        question=request.question,
        max_rows=request.max_rows,
        reference_time=active_reference_time,
        request_route=RequestRoute.ANALYSIS,
        request_reason_code=None,
        assistant_message=None,
        scope_supported=None,
        scope_rejection_reason=None,
        plan=None,
        retrieved_context=[],
        generated_sql=None,
        prepared_sql=None,
        sql_valid=None,
        sql_validation_error=None,
        business_sql_valid=None,
        business_sql_validation_error=None,
        query_risk=None,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        reviewed_by=None,
        approval_reason=None,
        query_rows=[],
        execution_error=None,
        final_answer=None,
        chart_spec=None,
        result_status=None,
        degradation_reason=None,
        retry_count=0,
        max_retries=max_retries,
        trace=[],
    )


def create_thread_config(thread_id: str) -> RunnableConfig:
    if not thread_id.strip():
        raise ValueError("thread_id must not be empty")

    return {"configurable": {"thread_id": thread_id}}


def create_domain_scope_node(gate: MetricDomainGate) -> AnalysisNode:
    def scope(state: AnalysisState) -> AnalysisStateUpdate:
        preflight = classify_preflight_request(state["question"])
        if preflight is not None:
            return {
                "request_route": preflight.route,
                "request_reason_code": preflight.reason_code,
                "assistant_message": preflight.message,
                "scope_supported": True,
                "scope_rejection_reason": None,
                "trace": [SCOPE_NODE],
            }

        if requests_role_elevation(
            state["question"],
            state["access_role"],
        ):
            return {
                "scope_supported": False,
                "scope_rejection_reason": "identity_mismatch",
                "trace": [SCOPE_NODE],
            }

        if requests_write_operation(state["question"]):
            return {
                "scope_supported": False,
                "scope_rejection_reason": "non_read_only",
                "trace": [SCOPE_NODE],
            }

        if requests_all_columns(state["question"]):
            return {
                "scope_supported": False,
                "scope_rejection_reason": "select_star_forbidden",
                "trace": [SCOPE_NODE],
            }

        sensitive_columns = requested_sensitive_columns(state["question"])
        if sensitive_columns:
            if state["access_role"] is AccessRole.ANALYST:
                return {
                    "scope_supported": False,
                    "scope_rejection_reason": "forbidden_column",
                    "query_risk": QueryRisk(
                        requires_approval=False,
                        sensitive_columns=sensitive_columns,
                        result_limit=state["max_rows"],
                    ),
                    "trace": [SCOPE_NODE],
                }
            sql = build_sensitive_read_sql(
                sensitive_columns,
                max_rows=state["max_rows"],
            )
            return {
                "scope_supported": True,
                "scope_rejection_reason": None,
                "generated_sql": sql,
                "prepared_sql": prepare_safe_sql(
                    sql,
                    max_rows=state["max_rows"],
                    access_role=state["access_role"],
                ),
                "sql_valid": True,
                "business_sql_valid": True,
                "trace": [SCOPE_NODE],
            }

        decision = gate.classify(state["question"])
        return {
            "scope_supported": decision.supported,
            "scope_rejection_reason": (
                decision.reason_code.value
                if decision.reason_code is not None
                else None
            ),
            "trace": [SCOPE_NODE],
        }

    return scope


def create_conversation_response_node() -> AnalysisNode:
    def respond(state: AnalysisState) -> AnalysisStateUpdate:
        if state["request_route"] == RequestRoute.ANALYSIS:
            raise ValueError("analysis requests cannot use the response node")
        if state["assistant_message"] is None:
            raise ValueError("assistant message is required")
        return {
            "final_answer": state["assistant_message"],
            "trace": [RESPOND_NODE],
        }

    return respond


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


def create_retrieve_node(
    tool: RetrievalTool | QueryAwareRetrievalTool,
) -> AnalysisNode:
    def retrieve(state: AnalysisState) -> AnalysisStateUpdate:
        plan = state["plan"]
        if plan is None:
            raise ValueError("analysis plan is required before retrieval")

        query_aware_method = getattr(type(tool), "retrieve_with_query", None)
        if query_aware_method is not None:
            evidence = tool.retrieve_with_query(
                query=state["question"],
                plan=plan,
            )
        else:
            evidence = tool.retrieve(plan)

        return {
            "retrieved_context": evidence,
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
                validation_error=(
                    state["business_sql_validation_error"]
                    or state["sql_validation_error"]
                ),
            ),
            "prepared_sql": None,
            "sql_valid": None,
            "business_sql_valid": None,
            "business_sql_validation_error": None,
            "query_risk": None,
            "approval_status": ApprovalStatus.NOT_REQUIRED,
            "reviewed_by": None,
            "approval_reason": None,
            "result_status": None,
            "degradation_reason": None,
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

        plan = state.get("plan")
        effective_max_rows = min(
            state["max_rows"],
            plan.limit if plan is not None else state["max_rows"],
        )
        try:
            prepared_sql = tool.validate(
                request_id=state["request_id"],
                user_id=state["user_id"],
                sql=sql,
                max_rows=effective_max_rows,
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


def create_sql_business_validation_node(
    tool: SQLBusinessConsistencyTool,
) -> AnalysisNode:
    def validate_business_sql(state: AnalysisState) -> AnalysisStateUpdate:
        sql = state["generated_sql"]
        plan = state["plan"]
        evidence = state["retrieved_context"]
        if sql is None or plan is None or not evidence:
            return {
                "business_sql_valid": False,
                "business_sql_validation_error": (
                    "generated SQL, plan, and evidence are required"
                ),
                "retry_count": state["retry_count"] + 1,
                "trace": [VALIDATE_BUSINESS_SQL_NODE],
            }

        try:
            tool.validate(sql=sql, plan=plan, evidence=evidence)
        except SQLBusinessConsistencyToolError as exc:
            return {
                "business_sql_valid": False,
                "business_sql_validation_error": str(exc),
                "retry_count": state["retry_count"] + 1,
                "trace": [VALIDATE_BUSINESS_SQL_NODE],
            }

        return {
            "business_sql_valid": True,
            "business_sql_validation_error": None,
            "trace": [VALIDATE_BUSINESS_SQL_NODE],
        }

    return validate_business_sql


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

        query_parameters: dict[str, object] = {}
        plan = state["plan"]
        if plan is not None and plan.time_range is not None:
            end_time = state["reference_time"]
            query_parameters = {
                "start_time": end_time - timedelta(days=plan.time_range.days),
                "end_time": end_time,
            }

        try:
            result = tool.execute(
                request_id=state["request_id"],
                user_id=state["user_id"],
                original_sql=original_sql,
                prepared_sql=prepared_sql,
                query_parameters=query_parameters,
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
            risk = state["query_risk"]
            if risk is None or not risk.sensitive_columns:
                raise ValueError("analysis plan is required before summarization")
            row_count = len(state["query_rows"])
            return {
                "final_answer": (
                    f"经管理员审批，受控查询已完成并返回 {row_count} 行数据。"
                ),
                "chart_spec": None,
                "result_status": AnalysisResultStatus.SUCCEEDED,
                "degradation_reason": None,
                "trace": [SUMMARIZE_NODE],
            }
        if state["execution_error"] is not None:
            raise ValueError("successful query execution is required before summarization")

        chart_spec = build_chart_spec(plan, state["query_rows"])
        try:
            answer = model.summarize(
                question=state["question"],
                plan=plan,
                rows=state["query_rows"],
            )
        except ModelInvocationError as exc:
            row_count = len(state["query_rows"])
            if row_count == 0:
                answer = (
                    "查询已成功完成，但总结服务暂时不可用。"
                    "当前没有符合条件的数据。"
                )
            else:
                answer = (
                    f"查询已成功完成并返回 {row_count} 行数据，"
                    "但自然语言总结服务暂时不可用，请查看表格结果。"
                )
            return {
                "final_answer": answer,
                "chart_spec": chart_spec,
                "result_status": AnalysisResultStatus.DEGRADED,
                "degradation_reason": str(exc),
                "trace": [SUMMARIZE_NODE],
            }

        return {
            "final_answer": answer,
            "chart_spec": chart_spec,
            "result_status": AnalysisResultStatus.SUCCEEDED,
            "degradation_reason": None,
            "trace": [SUMMARIZE_NODE],
        }

    return summarize


def create_fail_node() -> AnalysisNode:
    def fail(state: AnalysisState) -> AnalysisStateUpdate:
        reason = (
            state["execution_error"]
            or state["approval_reason"]
            or state["scope_rejection_reason"]
            or state["business_sql_validation_error"]
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
    business_validation_tool: SQLBusinessConsistencyTool | None = None,
    domain_gate: MetricDomainGate | None = None,
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
        validate_business_sql=(
            create_sql_business_validation_node(business_validation_tool)
            if business_validation_tool is not None
            else None
        ),
        scope=(
            create_domain_scope_node(domain_gate)
            if domain_gate is not None
            else None
        ),
        respond=create_conversation_response_node(),
    )


def route_after_scope(state: AnalysisState) -> str:
    if state.get("request_route", RequestRoute.ANALYSIS) != RequestRoute.ANALYSIS:
        return RESPOND_NODE
    if state["prepared_sql"] is not None:
        return ASSESS_RISK_NODE
    if state["scope_supported"] is True:
        return PLAN_NODE
    return FAIL_NODE


def route_after_sql_validation(state: AnalysisState) -> str:
    if state["sql_valid"] is True:
        return ASSESS_RISK_NODE
    if state["retry_count"] <= state["max_retries"]:
        return GENERATE_SQL_NODE
    return FAIL_NODE


def route_after_sql_safety(state: AnalysisState) -> str:
    if state["sql_valid"] is True:
        return VALIDATE_BUSINESS_SQL_NODE
    if state["retry_count"] <= state["max_retries"]:
        return GENERATE_SQL_NODE
    return FAIL_NODE


def route_after_sql_business_validation(state: AnalysisState) -> str:
    if state["business_sql_valid"] is True:
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


def _node_trace_status(
    node_name: str,
    update: AnalysisStateUpdate,
) -> TraceStatus:
    if update.get("result_status") is AnalysisResultStatus.DEGRADED:
        return TraceStatus.DEGRADED
    if update.get("execution_error") is not None:
        return TraceStatus.FAILED
    if node_name == SCOPE_NODE and update.get("scope_supported") is False:
        return TraceStatus.REJECTED
    if node_name == VALIDATE_SQL_NODE and update.get("sql_valid") is False:
        return TraceStatus.REJECTED
    if (
        node_name == VALIDATE_BUSINESS_SQL_NODE
        and update.get("business_sql_valid") is False
    ):
        return TraceStatus.REJECTED
    approval_status = update.get("approval_status")
    if approval_status is ApprovalStatus.PENDING:
        return TraceStatus.PENDING
    if approval_status is ApprovalStatus.REJECTED:
        return TraceStatus.REJECTED
    if node_name == FAIL_NODE:
        return TraceStatus.FAILED
    return TraceStatus.SUCCEEDED


def trace_workflow_node(
    node_name: str,
    node: AnalysisNode,
) -> AnalysisNode:
    component = f"node.{node_name}"

    def traced(state: AnalysisState) -> AnalysisStateUpdate:
        record_execution_trace(component, TraceStatus.STARTED)
        started_at = monotonic()
        try:
            inject_fault(component)
            update = node(state)
        except BaseException as exc:
            if type(exc).__name__ == "GraphInterrupt":
                record_execution_trace(
                    component,
                    TraceStatus.PENDING,
                    duration_ms=int((monotonic() - started_at) * 1000),
                )
            else:
                record_execution_trace(
                    component,
                    TraceStatus.FAILED,
                    duration_ms=int((monotonic() - started_at) * 1000),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            raise
        record_execution_trace(
            component,
            _node_trace_status(node_name, update),
            duration_ms=int((monotonic() - started_at) * 1000),
        )
        return update

    return traced


def build_analysis_graph(
    nodes: WorkflowNodes,
    *,
    checkpointer: BaseCheckpointSaver[object] | None = None,
    interrupt_before: list[str] | None = None,
) -> CompiledAnalysisGraph:
    graph = StateGraph(AnalysisState)

    if nodes.scope is not None:
        graph.add_node(
            SCOPE_NODE,
            trace_workflow_node(SCOPE_NODE, nodes.scope),
        )
    graph.add_node(
        RESPOND_NODE,
        trace_workflow_node(
            RESPOND_NODE,
            nodes.respond or create_conversation_response_node(),
        ),
    )
    graph.add_node(PLAN_NODE, trace_workflow_node(PLAN_NODE, nodes.plan))
    graph.add_node(
        RETRIEVE_NODE,
        trace_workflow_node(RETRIEVE_NODE, nodes.retrieve),
    )
    graph.add_node(
        GENERATE_SQL_NODE,
        trace_workflow_node(GENERATE_SQL_NODE, nodes.generate_sql),
    )
    graph.add_node(
        VALIDATE_SQL_NODE,
        trace_workflow_node(VALIDATE_SQL_NODE, nodes.validate_sql),
    )
    if nodes.validate_business_sql is not None:
        graph.add_node(
            VALIDATE_BUSINESS_SQL_NODE,
            trace_workflow_node(
                VALIDATE_BUSINESS_SQL_NODE,
                nodes.validate_business_sql,
            ),
        )
    graph.add_node(
        ASSESS_RISK_NODE,
        trace_workflow_node(ASSESS_RISK_NODE, nodes.assess_risk),
    )
    graph.add_node(
        REQUEST_APPROVAL_NODE,
        trace_workflow_node(REQUEST_APPROVAL_NODE, nodes.request_approval),
    )
    graph.add_node(
        EXECUTE_SQL_NODE,
        trace_workflow_node(EXECUTE_SQL_NODE, nodes.execute_sql),
    )
    graph.add_node(
        SUMMARIZE_NODE,
        trace_workflow_node(SUMMARIZE_NODE, nodes.summarize),
    )
    graph.add_node(FAIL_NODE, trace_workflow_node(FAIL_NODE, nodes.fail))

    if nodes.scope is None:
        graph.add_edge(START, PLAN_NODE)
    else:
        graph.add_edge(START, SCOPE_NODE)
        graph.add_conditional_edges(
            SCOPE_NODE,
            route_after_scope,
            {
                PLAN_NODE: PLAN_NODE,
                ASSESS_RISK_NODE: ASSESS_RISK_NODE,
                RESPOND_NODE: RESPOND_NODE,
                FAIL_NODE: FAIL_NODE,
            },
        )
    graph.add_edge(PLAN_NODE, RETRIEVE_NODE)
    graph.add_edge(RETRIEVE_NODE, GENERATE_SQL_NODE)
    graph.add_edge(GENERATE_SQL_NODE, VALIDATE_SQL_NODE)
    if nodes.validate_business_sql is None:
        graph.add_conditional_edges(
            VALIDATE_SQL_NODE,
            route_after_sql_validation,
            {
                ASSESS_RISK_NODE: ASSESS_RISK_NODE,
                GENERATE_SQL_NODE: GENERATE_SQL_NODE,
                FAIL_NODE: FAIL_NODE,
            },
        )
    else:
        graph.add_conditional_edges(
            VALIDATE_SQL_NODE,
            route_after_sql_safety,
            {
                VALIDATE_BUSINESS_SQL_NODE: VALIDATE_BUSINESS_SQL_NODE,
                GENERATE_SQL_NODE: GENERATE_SQL_NODE,
                FAIL_NODE: FAIL_NODE,
            },
        )
        graph.add_conditional_edges(
            VALIDATE_BUSINESS_SQL_NODE,
            route_after_sql_business_validation,
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
    graph.add_edge(RESPOND_NODE, END)
    graph.add_edge(FAIL_NODE, END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
    )
