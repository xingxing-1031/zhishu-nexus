from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from retail_analytics_agent.auth import require_session
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.settings import Settings, get_settings

_DENIED_COLUMNS = {
    AccessRole.ANALYST: frozenset({("refunds", "reason")}),
    AccessRole.ADMIN: frozenset(),
}

_SENSITIVE_QUERY_TERMS = {
    "refunds.reason": (
        "退款原因",
        "退款理由",
        "退款的具体原因",
        "refund reason",
    ),
}
_ROLE_SPOOF_TERMS = (
    "管理员",
    "admin",
    "administrator",
)
_WRITE_REQUEST_TERMS = (
    "删除",
    "清空",
    "新增",
    "插入",
    "修改",
    "delete ",
    "drop ",
    "insert ",
    "update ",
    "truncate ",
)
_ALL_COLUMN_REQUEST_TERMS = (
    "所有字段",
    "全部字段",
    "select *",
    "all columns",
)


def denied_columns_for_role(
    role: AccessRole,
) -> frozenset[tuple[str, str]]:
    return _DENIED_COLUMNS[role]


def requested_sensitive_columns(question: str) -> tuple[str, ...]:
    normalized = question.casefold()
    return tuple(
        column
        for column, terms in _SENSITIVE_QUERY_TERMS.items()
        if any(term.casefold() in normalized for term in terms)
    )


def requests_role_elevation(question: str, role: AccessRole) -> bool:
    if role is AccessRole.ADMIN:
        return False
    normalized = question.casefold()
    return any(term.casefold() in normalized for term in _ROLE_SPOOF_TERMS)


def requests_write_operation(question: str) -> bool:
    normalized = question.casefold()
    return any(term.casefold() in normalized for term in _WRITE_REQUEST_TERMS)


def requests_all_columns(question: str) -> bool:
    normalized = question.casefold()
    return any(
        term.casefold() in normalized
        for term in _ALL_COLUMN_REQUEST_TERMS
    )


def build_sensitive_read_sql(
    columns: tuple[str, ...],
    *,
    max_rows: int,
) -> str:
    if columns != ("refunds.reason",):
        raise ValueError("unsupported sensitive column request")
    result_limit = min(max_rows, 100)
    return (
        "SELECT refunds.refund_id AS refund_id, "
        "refunds.reason AS reason FROM refunds "
        "ORDER BY refunds.refund_id ASC "
        f"LIMIT {result_limit}"
    )


def get_access_context(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessContext:
    """Resolve trusted identity from a session or demo configuration."""
    if settings.auth_mode == "password":
        if settings.auth_session_secret is None:
            raise RuntimeError("authentication session secret is not configured")
        context = require_session(
            request,
            settings.auth_session_secret.get_secret_value(),
        )
        known_accounts = {
            (settings.auth_user_id, settings.auth_role),
            (settings.auth_admin_user_id, AccessRole.ADMIN),
        }
        if (context.user_id, context.role) not in known_accounts:
            raise HTTPException(status_code=401, detail="登录状态已经失效。")
        return context
    return AccessContext(
        user_id=settings.local_access_user_id,
        role=settings.local_access_role,
    )


class AuthorizationAction(StrEnum):
    DATASET_SELECT = "dataset.select"
    SCHEMA_READ = "schema.read"
    SQL_EXECUTE = "sql.execute"
    RAG_RETRIEVE = "rag.retrieve"
    EVIDENCE_RETURN = "evidence.return"
    TRACE_VIEW = "trace.view"
    APPROVAL_RESUME = "approval.resume"


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    action: str
    resource: str
    policy_version: str = "1.0"


@dataclass(frozen=True)
class AccessPolicy:
    """Permission rules attached to a caller; empty whitelist means allow all."""

    authorized_datasets: frozenset[str] = frozenset()
    expires_at: datetime | None = None
    policy_version: str = "1.0"


def _resource_dataset_id(resource: str) -> str | None:
    for prefix in ("dataset:", "schema:", "sql:"):
        if resource.startswith(prefix):
            return resource[len(prefix):]
    return None


def _resource_owner(resource: str) -> str | None:
    prefix = "trace:"
    if not resource.startswith(prefix):
        return None
    parts = resource[len(prefix):].split(":", 1)
    return parts[0] if parts else None


def authorize(
    user: AccessContext,
    action: str,
    resource: str,
    *,
    policy: AccessPolicy | None = None,
    purpose: str = "analysis",
) -> AuthorizationDecision:
    del purpose
    if policy is not None and policy.expires_at is not None:
        if datetime.now(UTC) > policy.expires_at:
            return AuthorizationDecision(
                allowed=False,
                reason="policy expired",
                action=action,
                resource=resource,
                policy_version=policy.policy_version,
            )
    if action == AuthorizationAction.APPROVAL_RESUME:
        allowed = user.role is AccessRole.ADMIN
        reason = "ok" if allowed else "approval resume requires admin role"
    elif action == AuthorizationAction.TRACE_VIEW:
        owner = _resource_owner(resource)
        allowed = (
            user.role is AccessRole.ADMIN
            or (owner is not None and owner == user.user_id)
        )
        reason = "ok" if allowed else "trace belongs to another user"
    elif _resource_dataset_id(resource) is not None:
        dataset_id = _resource_dataset_id(resource)
        allowed = (
            policy is None
            or not policy.authorized_datasets
            or dataset_id in policy.authorized_datasets
        )
        reason = "ok" if allowed else "dataset not authorized"
    else:
        allowed = True
        reason = "ok"
    return AuthorizationDecision(
        allowed=allowed,
        reason=reason,
        action=action,
        resource=resource,
        policy_version=(policy.policy_version if policy is not None else "1.0"),
    )


@dataclass
class PermissionAuditLog:
    entries: list[AuthorizationDecision] = field(default_factory=list)

    def record(self, decision: AuthorizationDecision) -> None:
        self.entries.append(decision)
