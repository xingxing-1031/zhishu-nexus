from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class KnowledgeAdapterError(RuntimeError):
    """Raised when the governed knowledge service cannot provide evidence."""


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=40)
    departments: tuple[str, ...] = Field(default=(), max_length=20)
    as_of: date | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=80)
    effective_from: date | None = None
    quote: str = Field(min_length=1, max_length=2000)
    score: float = Field(ge=0, le=1)
    permissions: tuple[str, ...] = Field(default=(), max_length=20)


class KnowledgeRetriever(Protocol):
    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]: ...


@dataclass(frozen=True)
class FixtureKnowledgeAdapter:
    evidence: tuple[KnowledgeEvidence, ...]

    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]:
        normalized = query.query.casefold()
        candidates = tuple(
            item for item in self.evidence
            if any(term in f"{item.title} {item.quote}".casefold() for term in normalized.split())
        )
        return (candidates or self.evidence)[:query.top_k]


@dataclass(frozen=True)
class HttpKnowledgeAdapter:
    base_url: str
    client: httpx.Client
    timeout_seconds: float = 10

    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]:
        if not self.base_url.startswith(("http://", "https://")):
            raise KnowledgeAdapterError("knowledge endpoint must be HTTP(S)")
        try:
            response = self.client.post(
                f"{self.base_url.rstrip('/')}/chat",
                json={
                    "question": query.query,
                    "user_id": query.user_id,
                    "role": query.role,
                    "departments": list(query.departments),
                    "as_of": query.as_of.isoformat() if query.as_of else None,
                    "top_k": query.top_k,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KnowledgeAdapterError("knowledge service unavailable") from exc
        try:
            raw_items = payload.get("evidence", payload.get("citations", []))
            return tuple(KnowledgeEvidence.model_validate(item) for item in raw_items)[:query.top_k]
        except (AttributeError, TypeError, ValidationError) as exc:
            raise KnowledgeAdapterError("knowledge response did not contain governed evidence") from exc


def evidence_to_tool_payload(items: tuple[KnowledgeEvidence, ...]) -> dict[str, Any]:
    return {
        "evidence": [
            {
                "source_id": item.source_id,
                "title": item.title,
                "version": item.version,
                "effective_from": item.effective_from.isoformat() if item.effective_from else None,
                "quote": item.quote,
                "score": item.score,
                "permissions": list(item.permissions),
            }
            for item in items
        ],
        "evidence_ids": [item.source_id for item in items],
    }
