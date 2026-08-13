from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from retail_analytics_agent.agent_models import (
    ContextSnapshot,
    OperationsReport,
    TaskPlan,
    ToolCallRecord,
    ToolResult,
)
from retail_analytics_agent.models import AccessContext
from retail_analytics_agent.reporting import ReportComposer
from retail_analytics_agent.tool_registry import ToolRegistry, ToolRegistryError


class OperationsWorkflowError(RuntimeError):
    pass


@dataclass
class OperationsState:
    request_id: str
    conversation_id: str
    question: str
    access_context: AccessContext
    task_plan: TaskPlan
    context: ContextSnapshot
    current_index: int = 0
    step_count: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    status: str = "running"
    report: OperationsReport | None = None


@dataclass
class OperationsWorkflow:
    registry: ToolRegistry
    composer: ReportComposer = field(default_factory=ReportComposer)

    def run(
        self,
        *,
        request_id: str,
        conversation_id: str,
        question: str,
        access_context: AccessContext,
        task_plan: TaskPlan,
        context: ContextSnapshot,
        findings: Sequence[str] = (),
    ) -> OperationsState:
        state = OperationsState(
            request_id=request_id,
            conversation_id=conversation_id,
            question=question,
            access_context=access_context,
            task_plan=task_plan,
            context=context,
        )
        while state.current_index < len(task_plan.subtasks):
            if state.step_count >= task_plan.max_steps:
                state.status = "degraded"
                state.limitations.append("达到任务最大步数，未继续调用工具。")
                break
            subtask = task_plan.subtasks[state.current_index]
            state.step_count += 1
            self._execute_subtask(state, subtask)
            state.current_index += 1

        if not self._has_required_evidence(state, task_plan):
            state.status = "refused"
            state.limitations.append("完成条件要求的数据或制度证据未全部获得。")
        elif state.status == "running":
            state.status = "succeeded"
        state.report = self.composer.compose(
            title=f"{task_plan.skill_id.value} 经营分析报告",
            question=question,
            findings=findings,
            tool_results=state.tool_results,
            tool_calls=state.tool_calls,
            limitations=state.limitations,
        )
        return state

    def _execute_subtask(self, state: OperationsState, subtask) -> None:
        for tool_name in subtask.required_tools:
            if tool_name not in self.registry.names():
                state.limitations.append(f"工具未注册：{tool_name}")
                state.status = "degraded"
                continue
            try:
                outcome = self.registry.call(
                    tool_name,
                    {
                        "question": state.question,
                        "subtask_id": subtask.id,
                        "evidence_ids": list(state.context.evidence_ids),
                    },
                    access_context=state.access_context,
                    request_id=state.request_id,
                    conversation_id=state.conversation_id,
                    idempotency_key=f"{state.request_id}:{subtask.id}:{tool_name}",
                )
            except ToolRegistryError as exc:
                state.status = "degraded"
                state.limitations.append(f"{tool_name} 调用失败：{exc}")
                continue
            state.tool_calls.append(outcome.record)
            state.tool_results.append(outcome.result)

    @staticmethod
    def _has_required_evidence(state: OperationsState, plan: TaskPlan) -> bool:
        successful = {result.tool_name for result in state.tool_results if result.status == "succeeded"}
        required = {
            tool
            for subtask in plan.subtasks
            for tool in subtask.required_tools
            if tool in {"sql.query", "knowledge.search"}
        }
        return required.issubset(successful)
