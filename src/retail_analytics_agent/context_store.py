from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ContextStoreError(RuntimeError):
    """Raised when a conversation cannot be read or updated safely."""


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = Field(min_length=1, max_length=12000)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=50)
    confirmed_constraints: tuple[str, ...] = Field(default=(), max_length=30)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(default="", max_length=12000)
    confirmed_constraints: tuple[str, ...] = Field(default=(), max_length=30)
    turns: tuple[ConversationTurn, ...] = Field(default=(), max_length=100)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationStore(Protocol):
    def create_or_get(self, conversation_id: str, user_id: str) -> ConversationRecord: ...

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        turn: ConversationTurn,
    ) -> ConversationRecord: ...

    def save_summary(
        self,
        conversation_id: str,
        user_id: str,
        summary: str,
        *,
        confirmed_constraints: tuple[str, ...] = (),
    ) -> ConversationRecord: ...

    def get(self, conversation_id: str, user_id: str) -> ConversationRecord | None: ...


@dataclass
class InMemoryConversationStore:
    """Bounded, user-isolated store used by tests and local evaluation."""

    max_turns: int = 100
    _records: OrderedDict[tuple[str, str], ConversationRecord] = field(
        default_factory=OrderedDict,
        init=False,
    )
    _lock: RLock = field(default_factory=RLock, init=False)

    def _key(self, conversation_id: str, user_id: str) -> tuple[str, str]:
        if not conversation_id.strip() or not user_id.strip():
            raise ContextStoreError("conversation_id and user_id are required")
        return conversation_id, user_id

    def create_or_get(self, conversation_id: str, user_id: str) -> ConversationRecord:
        key = self._key(conversation_id, user_id)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                record = ConversationRecord(
                    conversation_id=conversation_id,
                    user_id=user_id,
                )
                self._records[key] = record
            return record.model_copy(deep=True)

    def get(self, conversation_id: str, user_id: str) -> ConversationRecord | None:
        key = self._key(conversation_id, user_id)
        with self._lock:
            record = self._records.get(key)
            return record.model_copy(deep=True) if record is not None else None

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        turn: ConversationTurn,
    ) -> ConversationRecord:
        key = self._key(conversation_id, user_id)
        with self._lock:
            record = self.create_or_get(conversation_id, user_id)
            turns = (*record.turns, turn)[-self.max_turns :]
            constraints = tuple(dict.fromkeys(
                (*record.confirmed_constraints, *turn.confirmed_constraints)
            ))[-30:]
            updated = record.model_copy(update={
                "turns": turns,
                "confirmed_constraints": constraints,
                "updated_at": datetime.now(timezone.utc),
            })
            self._records[key] = updated
            return updated.model_copy(deep=True)

    def save_summary(
        self,
        conversation_id: str,
        user_id: str,
        summary: str,
        *,
        confirmed_constraints: tuple[str, ...] = (),
    ) -> ConversationRecord:
        key = self._key(conversation_id, user_id)
        if len(summary) > 12000:
            raise ContextStoreError("summary exceeds maximum size")
        with self._lock:
            record = self.create_or_get(conversation_id, user_id)
            constraints = tuple(dict.fromkeys(
                (*record.confirmed_constraints, *confirmed_constraints)
            ))[-30:]
            updated = record.model_copy(update={
                "summary": summary,
                "confirmed_constraints": constraints,
                "updated_at": datetime.now(timezone.utc),
            })
            self._records[key] = updated
            return updated.model_copy(deep=True)


@dataclass(frozen=True)
class PostgresConversationStore:
    """PostgreSQL adapter; schema is installed by migration 008."""

    connection_factory: object

    def _connection(self):
        return self.connection_factory()

    def create_or_get(self, conversation_id: str, user_id: str) -> ConversationRecord:
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO agent_conversations (conversation_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (conversation_id, user_id) DO UPDATE
                    SET updated_at = agent_conversations.updated_at
                RETURNING conversation_id, user_id, summary,
                    confirmed_constraints, updated_at
                """,
                (conversation_id, user_id),
            ).fetchone()
            if row is None:
                raise ContextStoreError("conversation upsert returned no row")
            turns = connection.execute(
                """
                SELECT request_id, role, content, evidence_ids,
                    confirmed_constraints, created_at
                FROM agent_conversation_turns
                WHERE conversation_id = %s AND user_id = %s
                ORDER BY created_at DESC LIMIT 100
                """,
                (conversation_id, user_id),
            ).fetchall()
        return ConversationRecord(
            **row,
            turns=tuple(ConversationTurn.model_validate(item) for item in reversed(turns)),
        )

    def get(self, conversation_id: str, user_id: str) -> ConversationRecord | None:
        try:
            return self.create_or_get(conversation_id, user_id)
        except Exception as exc:
            raise ContextStoreError("conversation lookup failed") from exc

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        turn: ConversationTurn,
    ) -> ConversationRecord:
        with self._connection() as connection:
            self.create_or_get(conversation_id, user_id)
            connection.execute(
                """
                INSERT INTO agent_conversation_turns
                    (conversation_id, user_id, request_id, role, content,
                     evidence_ids, confirmed_constraints)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (conversation_id, request_id) DO NOTHING
                """,
                (
                    conversation_id, user_id, turn.request_id, turn.role,
                    turn.content, list(turn.evidence_ids),
                    list(turn.confirmed_constraints),
                ),
            )
        return self.create_or_get(conversation_id, user_id)

    def save_summary(
        self,
        conversation_id: str,
        user_id: str,
        summary: str,
        *,
        confirmed_constraints: tuple[str, ...] = (),
    ) -> ConversationRecord:
        with self._connection() as connection:
            self.create_or_get(conversation_id, user_id)
            connection.execute(
                """
                UPDATE agent_conversations
                SET summary = %s,
                    confirmed_constraints = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE conversation_id = %s AND user_id = %s
                """,
                (summary, list(confirmed_constraints), conversation_id, user_id),
            )
        return self.create_or_get(conversation_id, user_id)
