from collections.abc import Iterator
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from retail_analytics_agent.settings import Settings, get_settings


DatabaseRow = dict[str, Any]
DatabaseConnection = Connection[DatabaseRow]

_REQUIRED_RELATIONS = (
    "public.orders",
    "public.order_items",
    "public.products",
    "public.refunds",
    "public.knowledge_chunks",
)


def connect_to_database(settings: Settings | None = None) -> DatabaseConnection:
    active_settings = settings or get_settings()
    return psycopg.connect(
        **active_settings.postgres_connection_kwargs,
        row_factory=dict_row,
    )


def get_database_connection() -> Iterator[DatabaseConnection]:
    with connect_to_database() as connection:
        yield connection


def check_database_readiness(settings: Settings | None = None) -> bool:
    """Check connectivity and the relations required by the analysis workflow."""
    try:
        with connect_to_database(settings) as connection:
            columns = ", ".join(
                f"to_regclass(%s) AS relation_{index}"
                for index in range(len(_REQUIRED_RELATIONS))
            )
            row = connection.execute(
                f"SELECT {columns}",
                _REQUIRED_RELATIONS,
            ).fetchone()
    except Exception:
        return False
    return bool(row) and all(row.values())
