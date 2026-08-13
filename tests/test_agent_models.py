import pytest
from pydantic import ValidationError

from retail_analytics_agent.agent_models import (
    ContextSnapshot,
    OperationsReport,
    SkillId,
    Subtask,
    TaskPlan,
)


def test_task_plan_rejects_duplicate_subtask_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        TaskPlan(
            goal="diagnose refunds",
            skill_id=SkillId.REFUND_DIAGNOSIS,
            subtasks=(
                Subtask(id="trend", description="query trend"),
                Subtask(id="trend", description="query channels"),
            ),
            completion_criteria=("data evidence",),
        )


def test_context_snapshot_preserves_evidence_and_budget() -> None:
    snapshot = ContextSnapshot(
        conversation_id="CONV-1",
        task_goal="explain refund rate",
        confirmed_constraints=("region=华东",),
        evidence_ids=("query:1", "policy:refund-v1"),
        token_budget=2000,
        token_estimate=1500,
    )

    assert snapshot.evidence_ids == ("query:1", "policy:refund-v1")
    assert snapshot.token_budget == 2000


def test_report_requires_at_least_one_finding() -> None:
    with pytest.raises(ValidationError):
        OperationsReport(
            title="复盘",
            executive_summary="summary",
            findings=[],
        )
