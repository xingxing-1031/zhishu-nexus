from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Literal, Protocol

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class WorkspacePayloadModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="ignore",
        populate_by_name=True,
    )


class WorkspaceTurnPayload(WorkspacePayloadModel):
    id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=4000)
    created_at: datetime
    duration_ms: int = Field(ge=0, le=3_600_000)
    status: Literal[
        "succeeded",
        "degraded",
        "answered",
        "needs_clarification",
        "pending",
        "rejected",
        "failed",
    ]
    summary: str = Field(min_length=1, max_length=50_000)
    outcome: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    chart_spec: dict[str, Any] | None = None
    rows: tuple[dict[str, Any], ...] = Field(default=(), max_length=100)
    stage_state: dict[str, str] = Field(default_factory=dict)
    follow_up_context: dict[str, Any] | None = None


class WorkspaceConversationPayload(WorkspacePayloadModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime
    turns: tuple[WorkspaceTurnPayload, ...] = Field(default=(), max_length=100)


class WorkspaceHistoryStore(Protocol):
    def list_for_user(
        self,
        user_id: str,
    ) -> tuple[WorkspaceConversationPayload, ...]: ...

    def put(
        self,
        user_id: str,
        conversation: WorkspaceConversationPayload,
    ) -> WorkspaceConversationPayload: ...

    def delete(self, user_id: str, conversation_id: str) -> bool: ...


def _bounded_conversation(
    conversation: WorkspaceConversationPayload,
    *,
    max_turns: int,
    max_rows: int,
) -> WorkspaceConversationPayload:
    turns = tuple(
        turn.model_copy(update={"rows": turn.rows[:max_rows]})
        for turn in conversation.turns[-max_turns:]
    )
    return conversation.model_copy(update={"turns": turns})


@dataclass
class InMemoryWorkspaceHistoryStore:
    max_conversations: int = 8
    max_turns: int = 8
    max_rows: int = 20
    _records: OrderedDict[
        tuple[str, str], WorkspaceConversationPayload
    ] = field(default_factory=OrderedDict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    def list_for_user(
        self,
        user_id: str,
    ) -> tuple[WorkspaceConversationPayload, ...]:
        with self._lock:
            records = (
                item.model_copy(deep=True)
                for (owner, _), item in self._records.items()
                if owner == user_id
            )
            return tuple(
                sorted(
                    records,
                    key=lambda item: (item.updated_at, item.id),
                    reverse=True,
                )[: self.max_conversations]
            )

    def put(
        self,
        user_id: str,
        conversation: WorkspaceConversationPayload,
    ) -> WorkspaceConversationPayload:
        bounded = _bounded_conversation(
            conversation,
            max_turns=self.max_turns,
            max_rows=self.max_rows,
        )
        with self._lock:
            self._records[(user_id, bounded.id)] = bounded
            current = self.list_for_user(user_id)
            retained = {item.id for item in current}
            for key in tuple(self._records):
                if key[0] == user_id and key[1] not in retained:
                    del self._records[key]
            return bounded.model_copy(deep=True)

    def delete(self, user_id: str, conversation_id: str) -> bool:
        with self._lock:
            return self._records.pop((user_id, conversation_id), None) is not None


@dataclass(frozen=True)
class PostgresWorkspaceHistoryStore:
    connection_factory: object
    max_conversations: int = 8
    max_turns: int = 8
    max_rows: int = 20

    def _connection(self):
        return self.connection_factory()

    def list_for_user(
        self,
        user_id: str,
    ) -> tuple[WorkspaceConversationPayload, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM workspace_conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC, conversation_id DESC
                LIMIT %s
                """,
                (user_id, self.max_conversations),
            ).fetchall()
        return tuple(
            WorkspaceConversationPayload.model_validate(row["payload"])
            for row in rows
        )

    def put(
        self,
        user_id: str,
        conversation: WorkspaceConversationPayload,
    ) -> WorkspaceConversationPayload:
        bounded = _bounded_conversation(
            conversation,
            max_turns=self.max_turns,
            max_rows=self.max_rows,
        )
        payload = bounded.model_dump(mode="json", by_alias=True)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO workspace_conversations
                    (user_id, conversation_id, title, payload,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, conversation_id) DO UPDATE
                SET title = EXCLUDED.title,
                    payload = EXCLUDED.payload,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    user_id,
                    bounded.id,
                    bounded.title,
                    Jsonb(payload),
                    bounded.created_at,
                    bounded.updated_at,
                ),
            )
            connection.execute(
                """
                DELETE FROM workspace_conversations
                WHERE user_id = %s
                  AND conversation_id NOT IN (
                      SELECT conversation_id
                      FROM workspace_conversations
                      WHERE user_id = %s
                      ORDER BY updated_at DESC, conversation_id DESC
                      LIMIT %s
                  )
                """,
                (user_id, user_id, self.max_conversations),
            )
        return bounded

    def delete(self, user_id: str, conversation_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM workspace_conversations
                WHERE user_id = %s AND conversation_id = %s
                """,
                (user_id, conversation_id),
            )
        return bool(cursor.rowcount)
