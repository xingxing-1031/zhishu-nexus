from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from retail_analytics_agent.models import (
    AnalysisDimension,
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisSort,
    ChartSpec,
    ChartType,
    RelativeTimeRange,
    RetrievalEvidence,
    SortDirection,
)
from retail_analytics_agent.settings import Settings, get_settings
from retail_analytics_agent.sql_safety import PreparedSQL


_CHECKPOINT_TYPES = (
    AnalysisDimension,
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisSort,
    ChartSpec,
    ChartType,
    RelativeTimeRange,
    RetrievalEvidence,
    SortDirection,
    PreparedSQL,
)


def create_checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)


@contextmanager
def open_postgres_checkpointer(
    settings: Settings | None = None,
) -> Iterator[PostgresSaver]:
    """Open an initialized PostgreSQL checkpointer for one graph lifetime."""
    active_settings = settings or get_settings()
    conninfo = make_conninfo(**active_settings.postgres_connection_kwargs)

    with Connection.connect(
        conninfo,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as connection:
        checkpointer = PostgresSaver(
            connection,
            serde=create_checkpoint_serializer(),
        )
        checkpointer.setup()
        yield checkpointer
