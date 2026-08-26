from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, Sequence

from retail_analytics_agent.agent_models import (
    ContextLayer,
    ContextLayerName,
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


def content_hash(text: str) -> str:
    encoded = text.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class ConservativeTokenCounter:
    def count(self, text: str) -> int:
        return estimate_tokens(text)


def render_layers(layers: Sequence[ContextLayer]) -> str:
    ordered = sorted(layers, key=lambda item: (item.priority, item.source_id))
    return "\n".join(
        f"[{item.layer.value}:{item.source_id}] {item.content}"
        for item in ordered
    )


def render_context_for_model(snapshot: ContextSnapshot) -> str:
    return render_layers(snapshot.layers)


@dataclass(frozen=True)
class ContextBuilder:
    store: ConversationStore
    token_counter: TokenCounter = ConservativeTokenCounter()

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
        system_rules: Sequence[str] = (),
        metrics_schema: Sequence[str] = (),
        allowed_evidence: Sequence[str] = (),
    ) -> ContextSnapshot:
        record = self.store.create_or_get(conversation_id, user_id)
        constraints = list(record.confirmed_constraints)
        question_lines = [f"access_role={access_context}"]
        question_lines.extend(constraints)
        question_lines.append(f"question={question}")
        question_lines.extend(
            f"subtask:{item.id}={item.description} ({item.status.value})"
            for item in task_plan.subtasks
        )
        evidence_ids = list(dict.fromkeys(evidence))
        recent_tools = [
            f"{call.tool_name}:{call.status}:{call.duration_ms}ms"
            for call in tool_calls[-8:]
        ]
        history_lines = list(recent_tools)
        if record.summary:
            history_lines.append(record.summary)
        history_lines.extend(
            f"{turn.role}: {turn.content}" for turn in record.turns
        )

        allowed = frozenset(allowed_evidence)
        layers: list[ContextLayer] = []
        excluded: list[str] = []
        seen_evidence_hashes: set[str] = set()

        def push(
            layer: ContextLayerName,
            source_id: str,
            priority: int,
            content: str,
        ) -> None:
            cost = self.token_counter.count(content)
            layers.append(
                ContextLayer(
                    layer=layer,
                    source_id=source_id,
                    priority=priority,
                    token_cost=cost,
                    permission_scope=access_context,
                    content_hash=content_hash(content),
                    content=content,
                )
            )

        for index, rule in enumerate(system_rules):
            push(ContextLayerName.SYSTEM_RULES, f"system_rule:{index}", 1, rule)
        for line in question_lines:
            push(ContextLayerName.QUESTION, "question", 2, line)
        for index, item in enumerate(metrics_schema):
            push(
                ContextLayerName.METRICS_SCHEMA,
                f"metric:{index}",
                3,
                f"metric_definition={item}",
            )
        for item in evidence_ids:
            if allowed and item not in allowed:
                excluded.append(f"no_permission:{item}")
                continue
            content = f"evidence={item}"
            digest = content_hash(content)
            if digest in seen_evidence_hashes:
                excluded.append(f"duplicate:{item}")
                continue
            seen_evidence_hashes.add(digest)
            push(ContextLayerName.EVIDENCE, item, 4, content)
        for index, line in enumerate(history_lines):
            push(ContextLayerName.HISTORY, f"history:{index}", 5, line)

        selected: list[ContextLayer] = []
        estimate = 0
        truncated = False
        for candidate in layers:
            cost = candidate.token_cost
            if estimate + cost <= token_budget:
                selected.append(candidate)
                estimate += cost
                continue
            if candidate.layer is ContextLayerName.QUESTION:
                raise ValueError("token_budget is too small for current goal")
            truncated = True
            excluded.append(f"budget:priority={candidate.priority}")
            break

        summary = "\n".join(item.content for item in selected)
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
            layers=tuple(selected),
            included_hashes=tuple(item.content_hash for item in selected),
            excluded_reasons=tuple(excluded),
            token_estimation_method=type(self.token_counter).__name__,
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
