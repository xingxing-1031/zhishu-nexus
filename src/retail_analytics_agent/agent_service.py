from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from retail_analytics_agent.agent_models import (
    AgentMode,
    AgentRequest,
    AgentResponse,
    AgentStreamEvent,
    AgentTaskStatus,
    SkillId,
    ToolCallRecord,
    ToolResult,
)
from retail_analytics_agent.agent_runtime import (
    AgentRunBudget,
    AgentRunGuard,
    AgentRunHalt,
    active_run_guard,
    agent_run_context,
    map_run_status_to_task_status,
)
from retail_analytics_agent.agent_tools import create_agent_tool_registry
from retail_analytics_agent.analysis_service import AnalysisRunner
from retail_analytics_agent.context_builder import ContextBuilder
from retail_analytics_agent.knowledge_adapter import (
    KnowledgeEvidence,
    KnowledgeRetriever,
)
from retail_analytics_agent.mcp_client import McpToolClient
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRejectedResponse,
    AnalysisResponse,
    AnalysisResultStatus,
    AnalysisRunningResponse,
    ApprovalRejectedResponse,
    ApprovalRequiredResponse,
    AssistantResponse,
)
from retail_analytics_agent.reporting import ReportComposer
from retail_analytics_agent.safety_rules import skill_system_rules
from retail_analytics_agent.skills import evaluate_completion
from retail_analytics_agent.task_planner import TaskPlanner, TaskPlanningError
from retail_analytics_agent.tool_registry import ToolCallOutcome, ToolRegistry

_KNOWLEDGE_QUERIES: dict[SkillId, str] = {
    SkillId.REFUND_DIAGNOSIS: (
        "企业售后退款制度中有哪些退款风险、人工复核条件和经营复盘要求？"
    ),
    SkillId.CHANNEL_COMPARISON: "企业渠道经营制度中有哪些渠道对比和复盘要求？",
    SkillId.PRODUCT_ANALYSIS: "企业商品经营制度中有哪些商品分析和复盘要求？",
    SkillId.WEEKLY_REPORT: (
        "企业经营周报制度中有哪些核心指标、证据引用和改进闭环要求？"
    ),
}


@dataclass
class EnterpriseAgentService:
    analysis_runner: AnalysisRunner
    context_builder: ContextBuilder
    task_planner: TaskPlanner
    knowledge: KnowledgeRetriever | None = None
    knowledge_departments: tuple[str, ...] = ()
    max_context_token_budget: int = 4000
    composer: ReportComposer = field(default_factory=ReportComposer)
    mcp_client: McpToolClient | None = None
    tool_registry: ToolRegistry | None = None
    run_budget: AgentRunBudget | None = None

    def __post_init__(self) -> None:
        if self.tool_registry is None:
            self.tool_registry = create_agent_tool_registry(
                self.analysis_runner,
                self.knowledge,
                self.mcp_client,
            )

    def run(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        *,
        persist_context: bool = True,
    ) -> AgentResponse:
        if request.user_id != access_context.user_id:
            raise PermissionError("agent request belongs to another user")
        guard = active_run_guard()
        if guard is not None:
            return self._run_impl(
                request,
                access_context,
                persist_context=persist_context,
            )
        owned = AgentRunGuard.create(
            request,
            AgentMode.DATA,
            self.run_budget or AgentRunBudget(),
        )
        try:
            with agent_run_context(owned):
                return self._run_impl(
                    request,
                    access_context,
                    persist_context=persist_context,
                )
        except AgentRunHalt as halt:
            owned.finish(halt.status, reason=halt.reason)
            return self._budget_response(request, halt)

    def _budget_response(
        self,
        request: AgentRequest,
        halt: AgentRunHalt,
    ) -> AgentResponse:
        status = map_run_status_to_task_status(halt.status)
        return AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=status,
            answer=f"本次分析因超出运行时预算而停止：{halt.reason}。",
            limitations=(halt.reason, str(halt)),
        )

    def _run_impl(
        self,
        request: AgentRequest,
        access_context: AccessContext,
        *,
        persist_context: bool,
    ) -> AgentResponse:
        if persist_context:
            self.context_builder.append_turn(
                request.conversation_id,
                request.user_id,
                request_id=f"{request.request_id}:user",
                role="user",
                content=request.question,
            )
        try:
            stored = self.context_builder.store.get(
                request.conversation_id,
                request.user_id,
            )
            previous_skill = next(
                (
                    item.removeprefix("last_skill=")
                    for item in reversed(stored.confirmed_constraints if stored else ())
                    if item.startswith("last_skill=")
                ),
                None,
            )
            plan = self.task_planner.plan(
                request.question,
                context=(
                    {"last_skill": previous_skill}
                    if previous_skill
                    else None
                ),
            )
        except TaskPlanningError as exc:
            return AgentResponse(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                status=AgentTaskStatus.REFUSED,
                limitations=(str(exc),),
            )
        skill = self.task_planner.registry.get(plan.skill_id)
        context = self.context_builder.build(
            request.conversation_id,
            request.question,
            plan,
            user_id=request.user_id,
            access_context=access_context.role.value,
            token_budget=min(
                request.token_budget,
                self.max_context_token_budget,
            ),
            system_rules=skill_system_rules(skill),
        )
        tool_calls: list[ToolCallRecord] = []
        tool_results: list[ToolResult] = []
        limitations: list[str] = []

        assert self.tool_registry is not None
        self._ensure_role_allows(skill.allowed_roles, access_context.role)
        self._ensure_skill_allows(skill.required_tools, "sql.query")
        analysis_question = request.question
        if plan.skill_id is SkillId.WEEKLY_REPORT:
            analysis_question = (
                f"{request.question}；数据分析口径：按渠道统计销售额和订单数"
            )
        analysis_outcome = self.tool_registry.call(
            "sql.query",
            {
                "request_id": request.request_id,
                "user_id": request.user_id,
                "question": analysis_question,
                "max_rows": request.max_rows,
                "dataset_id": request.dataset_id,
                "dataset_version": request.dataset_version,
                "context_snapshot": context.model_dump(mode="json"),
            },
            access_context=access_context,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            idempotency_key=f"{request.request_id}:sql",
        )
        tool_calls.append(analysis_outcome.record)
        tool_results.append(analysis_outcome.result)
        if analysis_outcome.result.status == "failed":
            return AgentResponse(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                status=AgentTaskStatus.FAILED,
                skill_id=plan.skill_id,
                task_plan=plan,
                context=context,
                tool_calls=tuple(tool_calls),
                limitations=(analysis_outcome.result.error or "数据库分析工具失败。",),
            )
        analysis = self._analysis_from_tool(analysis_outcome)
        if not isinstance(analysis, AnalysisResponse):
            return self._non_success_response(
                request, plan, context, analysis, tuple(tool_calls)
            )
        query_id = f"query:{request.request_id}"
        tool_results[-1] = ToolResult(
            tool_name="sql.query",
            status="succeeded",
            payload={
                "answer": analysis.answer,
                "rows": analysis.rows,
                "chart": (
                    analysis.chart_spec.model_dump(mode="json")
                    if analysis.chart_spec
                    else None
                ),
            },
            evidence_ids=(query_id, *analysis.evidence_source_ids),
        )

        knowledge_required = request.include_knowledge and any(
            "knowledge.search" in subtask.required_tools
            for subtask in plan.subtasks
        )
        knowledge_items = ()
        if knowledge_required:
            if self.knowledge is None:
                limitations.append("企业知识服务未配置，报告仅包含数据库证据。")
            else:
                self._ensure_skill_allows(
                    skill.required_tools,
                    "knowledge.search",
                )
                outcome = self.tool_registry.call(
                    "knowledge.search",
                    {
                        "query": _KNOWLEDGE_QUERIES[plan.skill_id],
                        "user_id": request.user_id,
                        "role": access_context.role.value,
                        "departments": self.knowledge_departments,
                        "top_k": 5,
                    },
                    access_context=access_context,
                    request_id=request.request_id,
                    conversation_id=request.conversation_id,
                    idempotency_key=f"{request.request_id}:knowledge",
                )
                tool_calls.append(outcome.record)
                tool_results.append(outcome.result)
                knowledge_status = outcome.result.status
                if knowledge_status == "succeeded":
                    knowledge_items = tuple(
                        KnowledgeEvidence.model_validate(item)
                        for item in outcome.result.payload.get("evidence", [])
                    )
                else:
                    limitations.append("企业知识服务暂时不可用，未生成制度归因。")
                if not knowledge_items and knowledge_status == "succeeded":
                    limitations.append("未检索到足够的企业制度证据，报告不做制度归因。")

        findings = [analysis.answer]
        findings.extend(
            f"制度证据：{item.title}（{item.version}）- {item.quote}"
            for item in knowledge_items[:3]
        )
        report = self.composer.compose(
            title="企业经营分析复盘报告",
            question=request.question,
            findings=findings,
            tool_results=tool_results,
            tool_calls=tool_calls,
            limitations=limitations,
        )
        exported_report = None
        if "report.export" in skill.required_tools:
            if "report.export" not in self.tool_registry.names():
                limitations.append("MCP 报告导出服务未配置。")
            else:
                export_outcome = self.tool_registry.call(
                    "report.export",
                    {
                        "report": report.model_dump(mode="json"),
                        "format": "markdown",
                    },
                    access_context=access_context,
                    request_id=request.request_id,
                    conversation_id=request.conversation_id,
                    idempotency_key=f"{request.request_id}:report-export",
                )
                tool_calls.append(export_outcome.record)
                tool_results.append(export_outcome.result)
                if export_outcome.result.status == "succeeded":
                    exported_report = str(
                        export_outcome.result.payload.get("markdown", "")
                    )
                else:
                    limitations.append("MCP 报告导出失败，结构化报告仍可用。")
        if tuple(limitations) != report.limitations:
            report = self.composer.compose(
                title="企业经营分析复盘报告",
                question=request.question,
                findings=findings,
                tool_results=tool_results,
                tool_calls=tool_calls,
                limitations=limitations,
            )
        completion = evaluate_completion(
            skill,
            evidence_ids=(*report.data_evidence, *report.document_evidence),
        )
        if not completion.satisfied:
            limitations.append(
                "完成条件要求的证据未全部获得："
                + "、".join(completion.missing)
            )
            report = self.composer.compose(
                title="企业经营分析复盘报告",
                question=request.question,
                findings=findings,
                tool_results=tool_results,
                tool_calls=tool_calls,
                limitations=limitations,
            )
        status = (
            AgentTaskStatus.DEGRADED
            if limitations or analysis.status is AnalysisResultStatus.DEGRADED
            else AgentTaskStatus.SUCCEEDED
        )
        if persist_context:
            self.context_builder.append_turn(
                request.conversation_id,
                request.user_id,
                request_id=f"{request.request_id}:assistant",
                role="assistant",
                content=report.executive_summary,
                evidence_ids=(*report.data_evidence, *report.document_evidence),
                confirmed_constraints=(f"last_skill={plan.skill_id.value}",),
            )
        return AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=status,
            skill_id=plan.skill_id,
            task_plan=plan,
            context=context,
            analysis=analysis,
            report=report,
            exported_report=exported_report,
            tool_calls=tuple(tool_calls),
            limitations=tuple(limitations),
        )

    @staticmethod
    def _analysis_from_tool(outcome: ToolCallOutcome):
        payload = outcome.result.payload.get("outcome")
        if not isinstance(payload, dict):
            raise RuntimeError("sql.query tool returned an invalid outcome")
        status = payload.get("status")
        candidates = (
            AnalysisResponse,
            ApprovalRequiredResponse,
            AnalysisRunningResponse,
            AnalysisRejectedResponse,
            ApprovalRejectedResponse,
            AssistantResponse,
        )
        for model in candidates:
            try:
                return model.model_validate(payload)
            except ValueError:
                continue
        raise RuntimeError(f"unsupported sql.query outcome: {status}")

    @staticmethod
    def _ensure_skill_allows(
        allowed_tools: tuple[str, ...],
        tool_name: str,
    ) -> None:
        if tool_name not in allowed_tools:
            raise PermissionError(
                f"skill tool allowlist does not permit {tool_name}"
            )

    @staticmethod
    def _ensure_role_allows(
        allowed_roles: tuple[AccessRole, ...],
        role: AccessRole,
    ) -> None:
        if role not in allowed_roles:
            raise PermissionError(
                f"skill is not allowed for role {role.value}"
            )

    def stream(
        self,
        request: AgentRequest,
        access_context: AccessContext,
    ) -> Iterator[AgentStreamEvent]:
        yield AgentStreamEvent(event="status", node="skill_route", message="业务 Skill 路由完成")
        yield AgentStreamEvent(event="status", node="context", message="服务端上下文构建完成")
        try:
            response = self.run(request, access_context)
        except Exception as exc:
            yield AgentStreamEvent(event="error", node="agent", message=str(exc))
            return
        yield AgentStreamEvent(event="status", node="tools", message="受治理工具调用完成")
        yield AgentStreamEvent(event="result", node="report", message="经营分析报告生成完成", response=response)

    @staticmethod
    def _non_success_response(request, plan, context, analysis, tool_calls):
        if isinstance(analysis, ApprovalRequiredResponse):
            status = AgentTaskStatus.PENDING
        elif isinstance(analysis, AnalysisRunningResponse):
            status = AgentTaskStatus.RUNNING
        elif isinstance(analysis, (AnalysisRejectedResponse, ApprovalRejectedResponse)):
            status = AgentTaskStatus.REFUSED
        elif isinstance(analysis, AssistantResponse):
            status = AgentTaskStatus.REFUSED
        else:
            status = AgentTaskStatus.FAILED
        return AgentResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status=status,
            skill_id=plan.skill_id,
            task_plan=plan,
            context=context,
            analysis=analysis,
            tool_calls=tool_calls,
            limitations=("结构化数据步骤未完成，未继续生成跨源报告。",),
        )
