from collections.abc import Iterator
from functools import lru_cache
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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


@lru_cache
def get_database_pool() -> ConnectionPool[DatabaseRow]:
    """Create one bounded pool for HTTP request connections."""
    settings = get_settings()
    connection_kwargs = {
        **settings.postgres_connection_kwargs,
        "row_factory": dict_row,
    }
    conninfo = str(connection_kwargs.pop("conninfo", ""))
    return ConnectionPool(
        conninfo=conninfo,
        kwargs=connection_kwargs,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        timeout=settings.database_pool_timeout_seconds,
        open=False,
    )


def open_database_pool() -> None:
    pool = get_database_pool()
    if pool.closed:
        pool.open(wait=True)


def close_database_pool() -> None:
    if get_database_pool.cache_info().currsize == 0:
        return
    pool = get_database_pool()
    if not pool.closed:
        pool.close()
    get_database_pool.cache_clear()


def get_database_connection() -> Iterator[DatabaseConnection]:
    open_database_pool()
    with get_database_pool().connection() as connection:
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
