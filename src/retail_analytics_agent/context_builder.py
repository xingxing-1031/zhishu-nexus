from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from retail_analytics_agent.agent_models import (
    ContextSnapshot,
    TaskPlan,
    ToolCallRecord,
)
from retail_analytics_agent.context_store import ConversationStore, ConversationTurn


def estimate_tokens(text: str) -> int:
    """Deterministic conservative estimate for mixed Chinese/English prompts."""
    if not text:
        return 0
    return max(1, (len(text) + 2) // 3)


@dataclass(frozen=True)
class ContextBuilder:
    store: ConversationStore

    def build(
        self,
        conversation_id: str,
        question: str,
        task_plan: TaskPlan,
        *,
        user_id: str,
        access_context: str = "analyst",
        evidence: Sequence[str] = (),
        tool_calls: Sequence[ToolCallRecord] = (),
        token_budget: int = 4000,
    ) -> ContextSnapshot:
        record = self.store.create_or_get(conversation_id, user_id)
        constraints = list(record.confirmed_constraints)
        current = [f"access_role={access_context}"]
        current.extend(constraints)
        current.append(f"question={question}")
        current.extend(
            f"subtask:{item.id}={item.description} ({item.status.value})"
            for item in task_plan.subtasks
        )
        evidence_ids = list(dict.fromkeys(evidence))
        recent_tools = [
            f"{call.tool_name}:{call.status}:{call.duration_ms}ms"
            for call in tool_calls[-8:]
        ]

        sections: list[tuple[str, list[str]]] = [
            ("goal", current),
            ("evidence", [f"evidence={item}" for item in evidence_ids]),
            ("tools", recent_tools),
            ("summary", [record.summary] if record.summary else []),
            ("history", [f"{turn.role}: {turn.content}" for turn in record.turns]),
        ]
        selected: list[str] = []
        estimate = 0
        truncated = False
        for index, (_name, values) in enumerate(sections):
            for value in values:
                cost = estimate_tokens(value)
                if estimate + cost <= token_budget:
                    selected.append(value)
                    estimate += cost
                else:
                    truncated = True
                    if index == 0:
                        raise ValueError("token_budget is too small for current goal")
                    break

        summary = "\n".join(selected)
        return ContextSnapshot(
            conversation_id=conversation_id,
            task_goal=task_plan.goal,
            summary=summary,
            confirmed_constraints=tuple(constraints),
            evidence_ids=tuple(evidence_ids),
            recent_tool_results=tuple(recent_tools),
            token_budget=token_budget,
            token_estimate=estimate,
            truncated=truncated,
        )

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        *,
        request_id: str,
        role: str,
        content: str,
        evidence_ids: tuple[str, ...] = (),
        confirmed_constraints: tuple[str, ...] = (),
    ) -> None:
        self.store.append_turn(
            conversation_id,
            user_id,
            ConversationTurn(
                request_id=request_id,
                role=role,
                content=content,
                evidence_ids=evidence_ids,
                confirmed_constraints=confirmed_constraints,
            ),
        )
