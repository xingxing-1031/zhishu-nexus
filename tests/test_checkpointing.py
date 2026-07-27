from unittest.mock import MagicMock, patch

from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from retail_analytics_agent.checkpointing import (
    create_checkpoint_serializer,
    open_postgres_checkpointer,
)
from retail_analytics_agent.models import AnalysisPlan, RetrievalEvidence
from retail_analytics_agent.settings import Settings
from retail_analytics_agent.sql_safety import PreparedSQL


def test_open_postgres_checkpointer_uses_settings_and_runs_setup() -> None:
    settings = Settings(
        postgres_db="retail_test",
        postgres_user="retail_user",
        postgres_password="secret value",
        postgres_host="db.internal",
        postgres_port=5544,
    )
    manager = MagicMock()
    connection = MagicMock()
    checkpointer = MagicMock()
    manager.__enter__.return_value = connection

    with patch(
        "retail_analytics_agent.checkpointing.Connection.connect",
        return_value=manager,
    ) as connect, patch(
        "retail_analytics_agent.checkpointing.PostgresSaver",
        return_value=checkpointer,
    ) as saver_class:
        with open_postgres_checkpointer(settings):
            pass

    conninfo = connect.call_args.args[0]
    parsed = conninfo_to_dict(conninfo)
    assert parsed == {
        "dbname": "retail_test",
        "user": "retail_user",
        "password": "secret value",
        "host": "db.internal",
        "port": "5544",
    }
    assert connect.call_args.kwargs == {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }
    assert saver_class.call_args.args == (connection,)
    assert saver_class.call_args.kwargs["serde"] is not None
    checkpointer.setup.assert_called_once_with()
    manager.__exit__.assert_called_once()


def test_checkpoint_serializer_restores_registered_state_types() -> None:
    serializer = create_checkpoint_serializer()
    values = [
        AnalysisPlan(
            analysis_goal="统计销售额",
            metrics=["sales_amount"],
            dimensions=["channel"],
        ),
        RetrievalEvidence(
            source_id="metric.sales_amount",
            content="paid orders.amount",
        ),
        PreparedSQL(
            sql="SELECT order_id FROM orders LIMIT 10",
            tables=("orders",),
            max_rows=10,
        ),
    ]

    restored = serializer.loads_typed(serializer.dumps_typed(values))

    assert restored == values
    assert isinstance(restored[0], AnalysisPlan)
    assert isinstance(restored[1], RetrievalEvidence)
    assert isinstance(restored[2], PreparedSQL)
