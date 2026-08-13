from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.agent_models import ContextSnapshot
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.operations_workflow import OperationsWorkflow
from retail_analytics_agent.skills import default_skill_registry
from retail_analytics_agent.task_planner import TaskPlanner, TaskPlanningError


class AgentEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_skill: str | None = None
    required_tools: tuple[str, ...] = ()
    requires_data: bool = False
    requires_document: bool = False
    expected_refusal: bool = False


class AgentEvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    routed_skill: str | None
    planned_tools: tuple[str, ...]
    executed_tools: tuple[str, ...]
    status: str
    refusal_correct: bool
    skill_correct: bool
    tool_allowlist_correct: bool
    evidence_complete: bool
    latency_ms: int = Field(ge=0)


class AgentEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    records: tuple[AgentEvaluationRecord, ...]
    skill_route_accuracy: float = Field(ge=0, le=1)
    refusal_accuracy: float = Field(ge=0, le=1)
    tool_allowlist_accuracy: float = Field(ge=0, le=1)
    evidence_completeness: float = Field(ge=0, le=1)


def load_cases(path: Path) -> tuple[AgentEvaluationCase, ...]:
    return tuple(
        AgentEvaluationCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def evaluate_cases(
    cases: tuple[AgentEvaluationCase, ...],
    workflow: OperationsWorkflow,
) -> AgentEvaluationReport:
    registry = default_skill_registry()
    planner = TaskPlanner(registry)
    records: list[AgentEvaluationRecord] = []
    for index, case in enumerate(cases, start=1):
        started = monotonic()
        routed = registry.route(case.question)
        routed_skill = routed.skill.id.value if routed.skill else None
        executed: tuple[str, ...] = ()
        planned: tuple[str, ...] = ()
        status = "refused"
        try:
            plan = planner.plan(case.question)
        except TaskPlanningError:
            plan = None
        if plan is not None:
            planned = tuple(dict.fromkeys(
                tool for subtask in plan.subtasks for tool in subtask.required_tools
            ))
            state = workflow.run(
                request_id=f"eval-{index}", conversation_id=f"eval-{index}",
                question=case.question,
                access_context=AccessContext(user_id="eval", role=AccessRole.ANALYST),
                task_plan=plan,
                context=ContextSnapshot(
                    conversation_id=f"eval-{index}", task_goal=plan.goal,
                ),
            )
            executed = tuple(dict.fromkeys(call.tool_name for call in state.tool_calls))
            status = state.status
        refusal_correct = (status == "refused") is case.expected_refusal
        skill_correct = routed_skill == case.expected_skill
        tool_allowlist_correct = set(executed).issubset(set(planned))
        # A skill may retrieve additional corroborating evidence. Completeness
        # checks the required minimum rather than penalising a safe extra source.
        evidence_complete = (
            (not case.requires_data or "sql.query" in executed)
            and (not case.requires_document or "knowledge.search" in executed)
        )
        records.append(AgentEvaluationRecord(
            case_id=case.case_id, routed_skill=routed_skill,
            planned_tools=planned, executed_tools=executed, status=status,
            refusal_correct=refusal_correct, skill_correct=skill_correct,
            tool_allowlist_correct=tool_allowlist_correct,
            evidence_complete=evidence_complete,
            latency_ms=int((monotonic() - started) * 1000),
        ))
    count = len(records) or 1
    return AgentEvaluationReport(
        dataset="agent_development_v1",
        records=tuple(records),
        skill_route_accuracy=sum(item.skill_correct for item in records) / count,
        refusal_accuracy=sum(item.refusal_correct for item in records) / count,
        tool_allowlist_accuracy=sum(item.tool_allowlist_correct for item in records) / count,
        evidence_completeness=sum(item.evidence_complete for item in records) / count,
    )
