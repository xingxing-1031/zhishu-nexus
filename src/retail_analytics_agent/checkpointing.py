from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from retail_analytics_agent.dataset_scope import DatasetScope
from retail_analytics_agent.knowledge import (
    MetricCatalog,
    MetricDefinition,
    SchemaCatalog,
    SchemaColumnDefinition,
    SchemaTableDefinition,
)
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisDimension,
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisResultStatus,
    AnalysisSort,
    ApprovalDecision,
    ApprovalStatus,
    ChartSpec,
    ChartType,
    QueryRisk,
    RelativeTimeRange,
    RetrievalEvidence,
    SortDirection,
)
from retail_analytics_agent.settings import Settings, get_settings
from retail_analytics_agent.sql_safety import PreparedSQL

_CHECKPOINT_TYPES = (
    AccessRole,
    DatasetScope,
    MetricCatalog,
    MetricDefinition,
    SchemaCatalog,
    SchemaColumnDefinition,
    SchemaTableDefinition,
    ApprovalDecision,
    ApprovalStatus,
    AnalysisDimension,
    AnalysisFilter,
    AnalysisFilterField,
    AnalysisFilterOperator,
    AnalysisMetric,
    AnalysisPlan,
    AnalysisResultStatus,
    AnalysisSort,
    ChartSpec,
    ChartType,
    RelativeTimeRange,
    RetrievalEvidence,
    QueryRisk,
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
