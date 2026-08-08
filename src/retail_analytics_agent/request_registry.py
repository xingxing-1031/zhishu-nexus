from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
)


class RequestClaimStatus(StrEnum):
    NEW = "new"
    EXISTING = "existing"
    CONFLICT = "conflict"


class RequestRunStatus(StrEnum):
    RUNNING = "running"
    PENDING = "pending"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RequestClaim:
    status: RequestClaimStatus
    run_status: RequestRunStatus
    user_id: str
    access_role: AccessRole
    error: str | None = None


class AnalysisRequestStore(Protocol):
    def claim(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> RequestClaim: ...

    def get(self, request_id: str) -> RequestClaim | None: ...

    def mark(
        self,
        request_id: str,
        status: RequestRunStatus,
        *,
        error: str | None = None,
    ) -> None: ...


CLAIM_REQUEST_SQL = """
WITH inserted AS (
    INSERT INTO analysis_request_registry (
        request_id,
        request_fingerprint,
        user_id,
        access_role,
        original_question,
        max_rows,
        status
    )
    VALUES (
        %(request_id)s,
        %(request_fingerprint)s,
        %(user_id)s,
        %(access_role)s,
        %(original_question)s,
        %(max_rows)s,
        'running'
    )
    ON CONFLICT (request_id) DO NOTHING
    RETURNING request_fingerprint, user_id, access_role, status, error
)
SELECT 'new' AS claim_status,
       request_fingerprint,
       user_id,
       access_role,
       status,
       error
FROM inserted
UNION ALL
SELECT 'existing' AS claim_status,
       request_fingerprint,
       user_id,
       access_role,
       status,
       error
FROM analysis_request_registry
WHERE request_id = %(request_id)s
  AND NOT EXISTS (SELECT 1 FROM inserted)
LIMIT 1;
"""

GET_REQUEST_SQL = """
SELECT request_fingerprint, user_id, access_role, status, error
FROM analysis_request_registry
WHERE request_id = %(request_id)s;
"""

MARK_REQUEST_SQL = """
UPDATE analysis_request_registry
SET status = %(status)s,
    error = %(error)s,
    updated_at = CURRENT_TIMESTAMP
WHERE request_id = %(request_id)s;
"""


def request_fingerprint(
    request: AnalysisRequest,
    access_context: AccessContext,
) -> str:
    payload = {
        "user_id": access_context.user_id,
        "access_role": access_context.role.value,
        "question": request.question,
        "max_rows": request.max_rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class DatabaseAnalysisRequestStore:
    def claim(
        self,
        request: AnalysisRequest,
        access_context: AccessContext,
    ) -> RequestClaim:
        fingerprint = request_fingerprint(request, access_context)
        params = {
            "request_id": request.request_id,
            "request_fingerprint": fingerprint,
            "user_id": access_context.user_id,
            "access_role": access_context.role.value,
            "original_question": request.question,
            "max_rows": request.max_rows,
        }
        with connect_to_database() as connection:
            row = connection.execute(CLAIM_REQUEST_SQL, params).fetchone()
        if row is None:
            raise RuntimeError("request registry did not return a claim")
        if row["request_fingerprint"] != fingerprint:
            return RequestClaim(
                status=RequestClaimStatus.CONFLICT,
                run_status=RequestRunStatus(row["status"]),
                user_id=row["user_id"],
                access_role=AccessRole(row["access_role"]),
                error=row["error"],
            )
        return RequestClaim(
            status=RequestClaimStatus(row["claim_status"]),
            run_status=RequestRunStatus(row["status"]),
            user_id=row["user_id"],
            access_role=AccessRole(row["access_role"]),
            error=row["error"],
        )

    def get(self, request_id: str) -> RequestClaim | None:
        with connect_to_database() as connection:
            row = connection.execute(
                GET_REQUEST_SQL,
                {"request_id": request_id},
            ).fetchone()
        if row is None:
            return None
        return RequestClaim(
            status=RequestClaimStatus.EXISTING,
            run_status=RequestRunStatus(row["status"]),
            user_id=row["user_id"],
            access_role=AccessRole(row["access_role"]),
            error=row["error"],
        )

    def mark(
        self,
        request_id: str,
        status: RequestRunStatus,
        *,
        error: str | None = None,
    ) -> None:
        with connect_to_database() as connection:
            cursor = connection.execute(
                MARK_REQUEST_SQL,
                {
                    "request_id": request_id,
                    "status": status.value,
                    "error": error,
                },
            )
            if cursor.rowcount != 1:
                raise RuntimeError("analysis request was not registered")
