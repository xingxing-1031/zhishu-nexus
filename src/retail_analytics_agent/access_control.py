from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.settings import get_settings


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


def get_access_context() -> AccessContext:
    """Return the server-configured identity until real auth is added."""
    settings = get_settings()
    return AccessContext(
        user_id=settings.local_access_user_id,
        role=settings.local_access_role,
    )
