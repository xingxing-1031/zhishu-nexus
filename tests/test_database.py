from contextlib import contextmanager
from unittest.mock import Mock

import retail_analytics_agent.database as database_module
from retail_analytics_agent.database import check_database_readiness


def _mock_connection(row):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = row

    @contextmanager
    def connect(_settings=None):
        yield connection

    return connect, connection


def test_database_readiness_requires_all_workflow_relations(monkeypatch) -> None:
    connect, connection = _mock_connection(
        {f"relation_{index}": object() for index in range(5)}
    )
    monkeypatch.setattr(database_module, "connect_to_database", connect)

    assert check_database_readiness() is True
    assert connection.execute.call_args.args[1] == (
        "public.orders",
        "public.order_items",
        "public.products",
        "public.refunds",
        "public.knowledge_chunks",
    )


def test_database_readiness_rejects_missing_relation(monkeypatch) -> None:
    connect, _ = _mock_connection(
        {
            "relation_0": object(),
            "relation_1": object(),
            "relation_2": None,
            "relation_3": object(),
            "relation_4": object(),
        }
    )
    monkeypatch.setattr(database_module, "connect_to_database", connect)

    assert check_database_readiness() is False


def test_database_readiness_rejects_connection_failure(monkeypatch) -> None:
    def fail_to_connect(_settings=None):
        raise OSError("database unavailable")

    monkeypatch.setattr(database_module, "connect_to_database", fail_to_connect)

    assert check_database_readiness() is False
