from datetime import datetime, timedelta

import pytest

import retail_analytics_agent.evaluation_snapshot as snapshot


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self) -> None:
        offset = timedelta(days=1)
        self.orders = {
            record_id: datetime.fromisoformat(value) - offset
            for record_id, value in snapshot.ORDER_TIMESTAMPS.items()
        }
        self.refunds = {
            record_id: datetime.fromisoformat(value) - offset
            for record_id, value in snapshot.REFUND_TIMESTAMPS.items()
        }
        self.closed = False
        self.unlocked = False

    def execute(self, sql, parameters=None):
        if "SELECT order_id AS record_id" in sql:
            return _Rows(
                [
                    {"record_id": key, "created_at": value}
                    for key, value in self.orders.items()
                ]
            )
        if "SELECT refund_id AS record_id" in sql:
            return _Rows(
                [
                    {"record_id": key, "created_at": value}
                    for key, value in self.refunds.items()
                ]
            )
        if sql.startswith("UPDATE orders"):
            self.orders[parameters["record_id"]] = parameters["created_at"]
        elif sql.startswith("UPDATE refunds"):
            self.refunds[parameters["record_id"]] = parameters["created_at"]
        elif "pg_advisory_unlock" in sql:
            self.unlocked = True
        return _Rows([])

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        self.closed = True


def test_temporary_snapshot_restores_timestamps_after_failure(monkeypatch) -> None:
    connection = _FakeConnection()
    original_orders = dict(connection.orders)
    original_refunds = dict(connection.refunds)
    monkeypatch.setattr(
        snapshot,
        "connect_to_database",
        lambda settings: connection,
    )

    with pytest.raises(RuntimeError, match="stop evaluation"):
        with snapshot.temporary_evaluation_snapshot(object()):
            assert connection.orders["ORD-001"] == datetime.fromisoformat(
                snapshot.ORDER_TIMESTAMPS["ORD-001"]
            )
            raise RuntimeError("stop evaluation")

    assert connection.orders == original_orders
    assert connection.refunds == original_refunds
    assert connection.unlocked is True
    assert connection.closed is True
