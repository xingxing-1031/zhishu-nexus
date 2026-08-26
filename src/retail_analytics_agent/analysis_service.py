from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from langgraph.types import Command

from retail_analytics_agent.access_control import (
    AccessPolicy,
    AuthorizationAction,
    PermissionAuditLog,
    authorize,
)
from retail_analytics_agent.approval import DatabaseApprovalAuditSink
from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.checkpoint_meta import (
    CheckpointMeta,
    CheckpointMetaStore,
)
from retail_analytics_agent.checkpointing import open_postgres_checkpointer
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.dataset_registry import DatasetRegistry
from retail_analytics_agent.dataset_scope import DatasetScopeResolver
from retail_analytics_agent.fault_injection import (
    FaultInjector,
    fault_injection_context,
)
from retail_analytics_agent.metric_domain import StructuredMetricDomainGate
from retail_analytics_agent.model_adapters import (
    StructuredAnalysisPlanner,
    StructuredResultSummarizer,
    StructuredSQLGenerator,
)
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisOutcome,
    AnalysisRejectedResponse,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisResultStatus,
    AnalysisRunningResponse,
    AnalysisStreamEvent,
    ApprovalRejectedResponse,
    ApprovalRequiredResponse,
    ApprovalResolutionRequest,
    ApprovalStatus,
    AssistantResponse,
    AssistantResponseStatus,
)
from retail_analytics_agent.request_registry import (
    AnalysisRequestStore,
    DatabaseAnalysisRequestStore,
    RequestClaim,
    RequestClaimStatus,
    RequestRunStatus,
)
from retail_analytics_agent.request_routing import RequestRoute
from retail_analytics_agent.resilience import RetryPolicy, workflow_time_budget
from retail_analytics_agent.schema_profiler import SchemaProfiler
from retail_analytics_agent.settings import get_settings
from retail_analytics_agent.tracing import (
    DatabaseExecutionTraceStore,
    ExecutionTraceEvent,
    ExecutionTraceResponse,
    ExecutionTraceStore,
    execution_trace_context,
)
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
    SQLConsistencyValidationTool,
    SQLGlotValidationTool,
)


class AnalysisRunError(RuntimeError):
    """Stable error for a workflow that cannot produce a successful response."""


class AnalysisRequestConflictError(RuntimeError):
    """Raised when one request_id is reused for different input."""


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

    def get_trace(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> ExecutionTraceResponse: ...


_NODE_STATUS_MESSAGES = {
    "scope": "请求类型与业务范围检查完成",
    "respond": "助手已生成说明",
    "plan": "分析问题已转换为结构化计划",
    "retrieve": "指标口径和数据结构检索完成",
    "generate_sql": "查询语句生成完成",
    "validate_sql": "查询安全校验完成",
    "validate_business_sql": "查询业务一致性校验完成",
    "assess_risk": "查询风险评估完成",
    "request_approval": "等待人工审批",
    "execute_sql": "零售数据库查询完成",
    "summarize": "分析结论和图表规格生成完成",
    "fail": "分析流程执行失败",
}

_PUBLIC_REJECTION_MESSAGES = {
    "unsupported_metric": (
        "当前演示支持销售额、订单数、销量、退款金额、退款笔数和平均订单金额；"
        "暂不支持库存、利润、物流或投诉分析。"
    ),
    "unsupported_dimension": (
        "当前演示支持按渠道、商品、品类、订单状态、退款状态和日期分析；"
        "暂不支持用户年龄、性别等维度。"
    ),
    "identity_mismatch": "不能通过问题内容提升权限，当前身份由服务器认证配置决定。",
    "non_read_only": "该请求包含写入或删除意图，已在访问数据库前拒绝。",
    "select_star_forbidden": (
        "为避免暴露无关字段，本系统不允许读取全部字段。请明确要查看的业务指标。"
    ),
    "forbidden_column": "当前分析员角色无权查看该敏感字段。",
    "dataset_not_found": "指定数据集不存在，请确认数据集标识。",
    "dataset_not_ready": "该数据集尚未完成质量检查与映射确认，不能用于分析。",
    "dataset_archived": "该数据集已归档，不能用于分析。",
    "dataset_mapping_unconfirmed": "该数据集尚未确认字段映射，不能用于分析。",
    "dataset_no_metrics": "该数据集还没有已确认的分析指标。",
    "dataset_unavailable": "当前环境未启用数据集分析。",
}


def _sanitize_trace_events(
    events: tuple[ExecutionTraceEvent, ...],
    viewer_role: AccessRole,
) -> tuple[ExecutionTraceEvent, ...]:
    if viewer_role is AccessRole.ADMIN:
        return events
    sanitized: list[ExecutionTraceEvent] = []
    for event in events:
        payload = event.payload
        if payload is not None and "dataset_schema" in payload:
            payload = {**payload, "dataset_schema": None}
        sanitized.append(
            event if payload is event.payload
            else event.model_copy(update={"payload": payload})
        )
    return tuple(sanitized)


@dataclass(frozen=True, slots=True)
class LangGraphAnalysisRunner:
    graph: CompiledAnalysisGraph
    request_store: AnalysisRequestStore | None = None
    trace_store: ExecutionTraceStore | None = None
    fault_injector: FaultInjector | None = None
    workflow_timeout_seconds: float = 120
    reference_time: datetime | None = None
    access_policy: AccessPolicy | None = None
    permission_audit: PermissionAuditLog | None = None
    checkpoint_meta: CheckpointMetaStore | None = None
    state_version: int = 1

    def run(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> AnalysisOutcome:
        if request.dataset_id:
            self._authorize_dataset(
                access_context,
                AuthorizationAction.DATASET_SELECT,
                request.dataset_id,
            )
        self._guard_checkpoint(request.request_id, access_context.user_id)
        claim = self._claim_request(request, access_context)
        if claim is not None and claim.status is RequestClaimStatus.EXISTING:
            return self._existing_outcome(request.request_id, claim)

        try:
            with (
                execution_trace_context(request.request_id, self.trace_store),
                fault_injection_context(self.fault_injector),
                workflow_time_budget(self.workflow_timeout_seconds),
            ):
                result = self.graph.invoke(
                    create_initial_state(
                        request,
                        access_context=access_context,
                        reference_time=self.reference_time,
                    ),
                    create_thread_config(request.request_id),
                )
            self._save_checkpoint_meta(
                request.request_id,
                access_context.user_id,
                result,
            )
            outcome = self._to_outcome(result)
        except Exception as exc:
            self._mark_request(
                request.request_id,
                RequestRunStatus.FAILED,
                error=str(exc),
            )
            raise
        self._mark_outcome(outcome)
        return outcome

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
        requester_id = snapshot.values["user_id"]
        requester_role = snapshot.values["access_role"]
        dataset_id = snapshot.values.get("dataset_id")
        self._guard_checkpoint(request_id, requester_id)
        self._authorize_dataset(
            AccessContext(user_id=requester_id, role=requester_role),
            AuthorizationAction.DATASET_SELECT,
            dataset_id,
        )
        self._authorize_decision(reviewer, AuthorizationAction.APPROVAL_RESUME, f"approval:{request_id}")
        if snapshot.values["approval_status"] != ApprovalStatus.PENDING:
            raise ValueError("approval request is not pending")
        if snapshot.next != ("request_approval",):
            raise ValueError("workflow is not waiting at the approval node")
        try:
            with (
                execution_trace_context(request_id, self.trace_store),
                fault_injection_context(self.fault_injector),
                workflow_time_budget(self.workflow_timeout_seconds),
            ):
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
            outcome = self._to_outcome(result)
        except Exception as exc:
            self._mark_request(
                request_id,
                RequestRunStatus.FAILED,
                error=str(exc),
            )
            raise
        self._mark_outcome(outcome)
        return outcome

    def get_status(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> AnalysisOutcome:
        snapshot = self.graph.get_state(create_thread_config(request_id))
        if not snapshot.values:
            claim = self.request_store.get(request_id) if self.request_store else None
            if claim is None:
                raise ValueError("analysis request was not found")
            self._check_viewer(claim, viewer)
            if claim.run_status is RequestRunStatus.FAILED:
                raise AnalysisRunError(claim.error or "analysis request failed")
            return AnalysisRunningResponse(
                request_id=request_id,
                access_role=claim.access_role,
            )
        requester_id = snapshot.values["user_id"]
        if (
            viewer.role is not AccessRole.ADMIN
            and viewer.user_id != requester_id
        ):
            raise PermissionError("analysis request belongs to another user")
        return self._snapshot_outcome(snapshot, snapshot.values["access_role"])

    def get_trace(
        self,
        request_id: str,
        viewer: AccessContext,
    ) -> ExecutionTraceResponse:
        if self.request_store is not None:
            claim = self.request_store.get(request_id)
            if claim is None:
                raise ValueError("analysis request was not found")
            self._check_viewer(claim, viewer)
            owner_id = claim.user_id
        else:
            snapshot = self.graph.get_state(create_thread_config(request_id))
            if not snapshot.values:
                raise ValueError("analysis request was not found")
            if (
                viewer.role is not AccessRole.ADMIN
                and viewer.user_id != snapshot.values["user_id"]
            ):
                raise PermissionError("analysis request belongs to another user")
            owner_id = snapshot.values["user_id"]
        self._authorize_decision(
            viewer,
            AuthorizationAction.TRACE_VIEW,
            f"trace:{owner_id}:{request_id}",
        )
        events = (
            self.trace_store.list_for_request(request_id)
            if self.trace_store is not None
            else ()
        )
        return ExecutionTraceResponse(
            request_id=request_id,
            events=_sanitize_trace_events(events, viewer.role),
        )

    def stream(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> Iterator[AnalysisStreamEvent]:
        self._guard_checkpoint(request.request_id, access_context.user_id)
        claim = self._claim_request(request, access_context)
        yield AnalysisStreamEvent(
            event="status",
            node=None,
            message="分析请求已接收",
        )
        if claim is not None and claim.status is RequestClaimStatus.EXISTING:
            outcome = self._existing_outcome(request.request_id, claim)
            yield from self._outcome_events(outcome)
            return

        last_node: str | None = None
        final_state = None
        try:
            with (
                execution_trace_context(request.request_id, self.trace_store),
                fault_injection_context(self.fault_injector),
                workflow_time_budget(self.workflow_timeout_seconds),
            ):
                for state in self.graph.stream(
                    create_initial_state(
                        request,
                        access_context=access_context,
                        reference_time=self.reference_time,
                    ),
                    create_thread_config(request.request_id),
                    stream_mode="values",
                ):
                    final_state = state
                    current_node = (
                        state["trace"][-1] if state["trace"] else None
                    )
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
        except Exception as exc:
            self._mark_request(
                request.request_id,
                RequestRunStatus.FAILED,
                error=str(exc),
            )
            raise

        if final_state is None:
            raise AnalysisRunError("analysis workflow returned no state")
        self._save_checkpoint_meta(
            request.request_id,
            access_context.user_id,
            final_state,
        )
        outcome = self._to_outcome(final_state)
        self._mark_outcome(outcome)
        yield from self._outcome_events(outcome)

    @staticmethod
    def _outcome_events(outcome: AnalysisOutcome) -> Iterator[AnalysisStreamEvent]:
        if isinstance(outcome, AnalysisRunningResponse):
            yield AnalysisStreamEvent(
                event="status",
                node=None,
                message="相同分析请求仍在处理中",
            )
            return
        if isinstance(outcome, ApprovalRequiredResponse):
            yield AnalysisStreamEvent(
                event="approval_required",
                node="request_approval",
                message="查询需要人工审批",
                approval=outcome,
            )
            return
        if isinstance(outcome, AssistantResponse):
            yield AnalysisStreamEvent(
                event="assistant_message",
                node="respond",
                message=outcome.answer,
                assistant=outcome,
            )
            return
        if isinstance(
            outcome,
            (AnalysisRejectedResponse, ApprovalRejectedResponse),
        ):
            terminal_node = next(
                (node for node in reversed(outcome.trace) if node != "fail"),
                "scope",
            )
            yield AnalysisStreamEvent(
                event="rejected",
                node=terminal_node,
                message=outcome.reason,
                rejection=outcome,
            )
            return
        yield AnalysisStreamEvent(
            event="result",
            node=None,
            message=(
                "分析完成（总结已降级）"
                if outcome.status is AnalysisResultStatus.DEGRADED
                else "分析完成"
            ),
            response=outcome,
        )

    def _claim_request(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> RequestClaim | None:
        if self.request_store is None:
            return None
        claim = self.request_store.claim(request, access_context)
        if claim.status is RequestClaimStatus.CONFLICT:
            raise AnalysisRequestConflictError(
                "request_id is already bound to different analysis input"
            )
        return claim

    def _existing_outcome(
        self,
        request_id: str,
        claim: RequestClaim,
    ) -> AnalysisOutcome:
        if claim.run_status is RequestRunStatus.FAILED:
            raise AnalysisRunError(claim.error or "analysis request failed")
        snapshot = self.graph.get_state(create_thread_config(request_id))
        if not snapshot.values:
            return AnalysisRunningResponse(
                request_id=request_id,
                access_role=claim.access_role,
            )
        return self._snapshot_outcome(snapshot, claim.access_role)

    def _snapshot_outcome(
        self,
        snapshot,
        access_role: AccessRole,
    ) -> AnalysisOutcome:
        values = snapshot.values
        if values["approval_status"] is ApprovalStatus.PENDING:
            return self._to_outcome(values)
        next_nodes = snapshot.next if isinstance(snapshot.next, tuple) else ()
        if next_nodes:
            return AnalysisRunningResponse(
                request_id=values["request_id"],
                access_role=access_role,
                trace=tuple(values["trace"]),
            )
        return self._to_outcome(values)

    def _guard_checkpoint(self, request_id: str, user_id: str) -> None:
        if self.checkpoint_meta is None:
            return
        meta = self.checkpoint_meta.get(request_id)
        if meta is None:
            return
        if meta.user_id != user_id:
            raise PermissionError("checkpoint belongs to another user")
        if meta.is_expired():
            raise RuntimeError("checkpoint has expired")
        if meta.state_version != self.state_version:
            raise RuntimeError("checkpoint state version mismatch")

    def _save_checkpoint_meta(self, request_id: str, user_id: str, result) -> None:
        if self.checkpoint_meta is None:
            return
        trace = result.get("trace", ()) if isinstance(result, Mapping) else ()
        self.checkpoint_meta.save(
            CheckpointMeta(
                request_id=request_id,
                user_id=user_id,
                state_version=self.state_version,
                last_completed_node=trace[-1] if trace else None,
            )
        )

    def _authorize_dataset(
        self,
        user: AccessContext,
        action: str,
        dataset_id: str | None,
    ) -> None:
        if not dataset_id:
            return
        self._authorize_decision(user, action, f"dataset:{dataset_id}")

    def _authorize_decision(
        self,
        user: AccessContext,
        action: str,
        resource: str,
    ) -> None:
        decision = authorize(
            user,
            action,
            resource,
            policy=self.access_policy,
        )
        if self.permission_audit is not None:
            self.permission_audit.record(decision)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    @staticmethod
    def _check_viewer(claim: RequestClaim, viewer: AccessContext) -> None:
        if (
            viewer.role is not AccessRole.ADMIN
            and viewer.user_id != claim.user_id
        ):
            raise PermissionError("analysis request belongs to another user")

    def _mark_outcome(self, outcome: AnalysisOutcome) -> None:
        if isinstance(outcome, ApprovalRequiredResponse):
            status = RequestRunStatus.PENDING
        elif isinstance(
            outcome,
            (AnalysisRejectedResponse, ApprovalRejectedResponse),
        ):
            status = RequestRunStatus.REJECTED
        elif isinstance(outcome, AnalysisRunningResponse):
            status = RequestRunStatus.RUNNING
        elif isinstance(outcome, AssistantResponse):
            status = RequestRunStatus.COMPLETED
        elif outcome.status is AnalysisResultStatus.DEGRADED:
            status = RequestRunStatus.DEGRADED
        else:
            status = RequestRunStatus.COMPLETED
        self._mark_request(outcome.request_id, status)

    def _mark_request(
        self,
        request_id: str,
        status: RequestRunStatus,
        *,
        error: str | None = None,
    ) -> None:
        if self.request_store is not None:
            self.request_store.mark(request_id, status, error=error)

    @staticmethod
    def _to_outcome(result) -> AnalysisOutcome:
        request_route = RequestRoute(
            result.get("request_route", RequestRoute.ANALYSIS)
        )
        if request_route != RequestRoute.ANALYSIS:
            answer = result["final_answer"] or result.get("assistant_message")
            reason_code = result.get("request_reason_code")
            if answer is None or reason_code is None:
                raise AnalysisRunError("assistant response is incomplete")
            return AssistantResponse(
                request_id=result["request_id"],
                status=(
                    AssistantResponseStatus.NEEDS_CLARIFICATION
                    if request_route == RequestRoute.CLARIFICATION
                    else AssistantResponseStatus.ANSWERED
                ),
                access_role=result["access_role"],
                reason_code=reason_code,
                answer=answer,
                trace=tuple(result["trace"]),
            )
        if result["scope_supported"] is False:
            reason_code = (
                result["scope_rejection_reason"] or "unsupported_metric"
            )
            return AnalysisRejectedResponse(
                request_id=result["request_id"],
                access_role=result["access_role"],
                reason_code=reason_code,
                reason=_PUBLIC_REJECTION_MESSAGES.get(
                    reason_code,
                    "当前分析能力不支持该请求，请换一种业务问题。",
                ),
                trace=tuple(result["trace"]),
            )
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
        if result["business_sql_valid"] is False:
            raise AnalysisRunError(
                result["business_sql_validation_error"]
                or "SQL business consistency validation failed"
            )
        plan = result["plan"]
        answer = result["final_answer"]
        if answer is None:
            raise AnalysisRunError("analysis workflow returned an incomplete result")

        return AnalysisResponse(
            request_id=result["request_id"],
            status=(
                result["result_status"]
                or AnalysisResultStatus.SUCCEEDED
            ),
            access_role=result["access_role"],
            answer=answer,
            plan=plan,
            rows=result["query_rows"],
            chart_spec=result["chart_spec"],
            evidence_source_ids=tuple(
                item.source_id for item in result["retrieved_context"]
            ),
            retry_count=result["retry_count"],
            degradation_reason=result["degradation_reason"],
            trace=tuple(result["trace"]),
        )


def get_analysis_runner() -> Iterator[AnalysisRunner]:
    settings = get_settings()
    audit_sink = DatabaseAuditSink()
    approval_audit_sink = DatabaseApprovalAuditSink()
    request_store = DatabaseAnalysisRequestStore()
    trace_store = DatabaseExecutionTraceStore()
    retry_policy = RetryPolicy(
        max_attempts=settings.model_retry_max_attempts,
        initial_backoff_seconds=(
            settings.model_retry_initial_backoff_seconds
        ),
    )
    with (
        httpx.Client(
            base_url=settings.active_model_base_url,
            headers=settings.model_client_headers,
            timeout=settings.active_model_timeout_seconds,
        ) as model_client,
        connect_to_database(settings) as query_connection,
        open_postgres_checkpointer(settings) as checkpointer,
    ):
        dataset_resolver = DatasetScopeResolver(
            DatasetRegistry(),
            SchemaProfiler(),
            connect_to_database,
        )
        nodes = create_workflow_nodes(
            domain_gate=StructuredMetricDomainGate(
                model_client,
                model=settings.active_model_name,
                protocol=settings.model_provider,
                timeout_seconds=settings.active_model_timeout_seconds,
            ),
            planner=StructuredAnalysisPlanner(
                model_client,
                model=settings.active_model_name,
                protocol=settings.model_provider,
                timeout_seconds=settings.active_model_timeout_seconds,
                retry_policy=retry_policy,
            ),
            retrieval_tool=CatalogRetrievalTool(),
            sql_generator=StructuredSQLGenerator(
                model_client,
                model=settings.active_model_name,
                protocol=settings.model_provider,
                timeout_seconds=settings.active_model_timeout_seconds,
                retry_policy=retry_policy,
            ),
            validation_tool=SQLGlotValidationTool(audit_sink),
            business_validation_tool=SQLConsistencyValidationTool(),
            approval_audit_sink=approval_audit_sink,
            execution_tool=SafeSQLExecutionTool(
                query_connection,
                audit_sink,
            ),
            summarizer=StructuredResultSummarizer(
                model_client,
                model=settings.active_model_name,
                protocol=settings.model_provider,
                timeout_seconds=settings.active_model_timeout_seconds,
                retry_policy=retry_policy,
            ),
            dataset_resolver=dataset_resolver,
            dataset_audit_sink=audit_sink,
        )
        yield LangGraphAnalysisRunner(
            build_analysis_graph(nodes, checkpointer=checkpointer),
            request_store=request_store,
            trace_store=trace_store,
            workflow_timeout_seconds=settings.workflow_timeout_seconds,
        )
