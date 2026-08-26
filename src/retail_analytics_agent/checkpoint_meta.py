from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

# Three state boundaries:
# - Working State: transient per-node values held in AnalysisState that can be
#   recomputed (generated_sql, query_rows, trace) and are not meant to survive.
# - Checkpoint: the recoverable full workflow state, persisted by langgraph as
#   channel_values plus this CheckpointMeta (version / expiry / ownership).
# - Conversation Memory: cross-request ConversationRecord kept per
#   (conversation_id, user_id) in the conversation store.


@dataclass(frozen=True)
class CheckpointMeta:
    request_id: str
    user_id: str
    state_version: int = 1
    last_completed_node: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now if now is not None else datetime.now(timezone.utc)
        return current > self.expires_at


class CheckpointMetaStore(Protocol):
    def save(self, meta: CheckpointMeta) -> None: ...

    def get(self, request_id: str) -> CheckpointMeta | None: ...


@dataclass
class InMemoryCheckpointMetaStore:
    _entries: dict[str, CheckpointMeta] = field(default_factory=dict)

    def save(self, meta: CheckpointMeta) -> None:
        self._entries[meta.request_id] = meta

    def get(self, request_id: str) -> CheckpointMeta | None:
        return self._entries.get(request_id)
