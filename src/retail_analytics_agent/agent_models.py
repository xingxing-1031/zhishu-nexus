from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.models import AnalysisOutcome


class AgentStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkillId(StrEnum):
    REFUND_DIAGNOSIS = "refund_diagnosis"
    CHANNEL_COMPARISON = "channel_comparison"
    PRODUCT_ANALYSIS = "product_analysis"
    WEEKLY_REPORT = "weekly_report"


class AgentMode(StrEnum):
    GENERAL = "general"
    KNOWLEDGE = "knowledge"
    DATA = "data"
    COLLABORATION = "collaboration"


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    REFUSED = "refused"
    FAILED = "failed"


class AgentStep(AgentStrictModel):
    agent: str = Field(min_length=1, max_length=80)
    task: str = Field(min_length=1, max_length=500)
    status: AgentTaskStatus = AgentTaskStatus.PENDING


class AgentReview(AgentStrictModel):
    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    limitations: tuple[str, ...] = Field(default=(), max_length=20)


class KnowledgeEvidenceView(AgentStrictModel):
    source_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=2000)
    score: float = Field(ge=0, le=1)
    effective_from: str | None = Field(default=None, max_length=80)


class Subtask(AgentStrictModel):
    id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    required_tools: tuple[str, ...] = Field(default=(), max_length=8)
    status: AgentTaskStatus = AgentTaskStatus.PENDING


class TaskPlan(AgentStrictModel):
    goal: str = Field(min_length=1, max_length=500)
    skill_id: SkillId
    subtasks: tuple[Subtask, ...] = Field(min_length=1, max_length=12)
    completion_criteria: tuple[str, ...] = Field(min_length=1, max_length=12)
    max_steps: int = Field(default=8, ge=1, le=30)

    @model_validator(mode="after")
    def validate_plan(self) -> TaskPlan:
        ids = [item.id for item in self.subtasks]
        if len(ids) != len(set(ids)):
            raise ValueError("subtask ids must be unique")
        if len(self.subtasks) > self.max_steps:
            raise ValueError("subtasks cannot exceed max_steps")
        return self


class ContextSnapshot(AgentStrictModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    task_goal: str = Field(min_length=1, max_length=500)
    summary: str = ""
    confirmed_constraints: tuple[str, ...] = Field(default=(), max_length=30)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=50)
    recent_tool_results: tuple[str, ...] = Field(default=(), max_length=20)
    token_budget: int = Field(default=4000, ge=256, le=32000)
    token_estimate: int = Field(default=0, ge=0)
    truncated: bool = False


class ToolCallRecord(AgentStrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    input_hash: str = Field(min_length=64, max_length=64)
    status: str = Field(min_length=1, max_length=40)
    duration_ms: int = Field(default=0, ge=0)
    error_type: str | None = Field(default=None, max_length=120)


class ReportFinding(AgentStrictModel):
    statement: str = Field(min_length=1, max_length=1000)
    data_evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    document_evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    confidence: str = Field(default="supported", max_length=40)


class OperationsReport(AgentStrictModel):
    title: str = Field(min_length=1, max_length=200)
    executive_summary: str = Field(min_length=1, max_length=3000)
    findings: tuple[ReportFinding, ...] = Field(min_length=1, max_length=20)
    charts: tuple[dict[str, Any], ...] = Field(default=(), max_length=10)
    data_evidence: tuple[str, ...] = Field(default=(), max_length=50)
    document_evidence: tuple[str, ...] = Field(default=(), max_length=50)
    limitations: tuple[str, ...] = Field(default=(), max_length=20)


class ToolResult(AgentStrictModel):
    tool_name: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=50)
    error: str | None = Field(default=None, max_length=1000)


class AgentRequest(AgentStrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    max_rows: int = Field(default=20, ge=1, le=1000)
    token_budget: int = Field(default=4000, ge=256, le=32000)
    include_knowledge: bool = True


class AgentResponse(AgentStrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    status: AgentTaskStatus
    skill_id: SkillId | None = None
    task_plan: TaskPlan | None = None
    context: ContextSnapshot | None = None
    analysis: AnalysisOutcome | None = None
    report: OperationsReport | None = None
    exported_report: str | None = Field(default=None, max_length=50000)
    tool_calls: tuple[ToolCallRecord, ...] = Field(default=(), max_length=50)
    limitations: tuple[str, ...] = Field(default=(), max_length=20)
    agent_mode: AgentMode | None = None
    agents: tuple[str, ...] = Field(default=(), max_length=8)
    agent_steps: tuple[AgentStep, ...] = Field(default=(), max_length=8)
    answer: str = Field(default="", max_length=12000)
    knowledge_evidence: tuple[KnowledgeEvidenceView, ...] = Field(
        default=(),
        max_length=20,
    )
    review: AgentReview | None = None


class AgentEventType(StrEnum):
    STATUS = "status"
    RESULT = "result"
    ERROR = "error"


class AgentStreamEvent(AgentStrictModel):
    event: AgentEventType
    node: str | None = Field(default=None, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    response: AgentResponse | None = None
