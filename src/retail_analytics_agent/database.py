from collections.abc import Iterator
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from retail_analytics_agent.settings import Settings, get_settings


DatabaseRow = dict[str, Any]
DatabaseConnection = Connection[DatabaseRow]


def connect_to_database(settings: Settings | None = None) -> DatabaseConnection:
    active_settings = settings or get_settings()
    return psycopg.connect(
        **active_settings.postgres_connection_kwargs,
        row_factory=dict_row,
    )


def get_database_connection() -> Iterator[DatabaseConnection]:
    with connect_to_database() as connection:
        yield connection
