from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.settings import get_settings


_DENIED_COLUMNS = {
    AccessRole.ANALYST: frozenset({("refunds", "reason")}),
    AccessRole.ADMIN: frozenset(),
}


def denied_columns_for_role(
    role: AccessRole,
) -> frozenset[tuple[str, str]]:
    return _DENIED_COLUMNS[role]


def get_access_context() -> AccessContext:
    """Return the server-configured identity until real auth is added."""
    settings = get_settings()
    return AccessContext(
        user_id=settings.local_access_user_id,
        role=settings.local_access_role,
    )
