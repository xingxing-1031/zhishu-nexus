from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.settings import Settings


EVALUATION_SNAPSHOT_LOCK_ID = 2_026_081_612

ORDER_TIMESTAMPS = {
    "ORD-001": "2026-08-14T12:00:00+08:00",
    "ORD-002": "2026-08-11T12:00:00+08:00",
    "ORD-003": "2026-07-02T12:00:00+08:00",
    "ORD-004": "2026-08-15T12:00:00+08:00",
    "ORD-005": "2026-08-04T12:00:00+08:00",
    "ORD-006": "2026-08-08T12:00:00+08:00",
    "ORD-007": "2026-08-13T12:00:00+08:00",
    "ORD-008": "2026-07-29T12:00:00+08:00",
    "ORD-009": "2026-07-22T12:00:00+08:00",
    "ORD-010": "2026-06-17T12:00:00+08:00",
}

REFUND_TIMESTAMPS = {
    "REF-001": "2026-08-15T12:00:00+08:00",
    "REF-002": "2026-08-06T12:00:00+08:00",
    "REF-003": "2026-08-01T12:00:00+08:00",
    "REF-004": "2026-07-07T12:00:00+08:00",
    "REF-005": "2026-07-27T12:00:00+08:00",
    "REF-006": "2026-08-16T00:00:00+08:00",
}


class EvaluationSnapshotError(RuntimeError):
    """Raised when the development database is not the expected seed set."""


def _timestamp_rows(
    values: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "record_id": record_id,
            "created_at": datetime.fromisoformat(created_at),
        }
        for record_id, created_at in values.items()
    )


def _replace_timestamps(
    connection,
    *,
    table: str,
    id_column: str,
    rows: tuple[dict[str, object], ...],
) -> None:
    sql = (
        f"UPDATE {table} SET created_at = %(created_at)s "
        f"WHERE {id_column} = %(record_id)s"
    )
    for row in rows:
        connection.execute(sql, row)


@contextmanager
def temporary_evaluation_snapshot(
    settings: Settings,
) -> Iterator[None]:
    """Expose the fixed W6 snapshot and restore the demo timestamps afterward."""

    connection = connect_to_database(settings)
    original_orders: tuple[dict[str, object], ...] = ()
    original_refunds: tuple[dict[str, object], ...] = ()
    locked = False
    try:
        connection.execute(
            "SELECT pg_advisory_lock(%(lock_id)s)",
            {"lock_id": EVALUATION_SNAPSHOT_LOCK_ID},
        )
        locked = True
        original_orders = tuple(
            connection.execute(
                "SELECT order_id AS record_id, created_at FROM orders"
            ).fetchall()
        )
        original_refunds = tuple(
            connection.execute(
                "SELECT refund_id AS record_id, created_at FROM refunds"
            ).fetchall()
        )
        if {row["record_id"] for row in original_orders} != set(
            ORDER_TIMESTAMPS
        ):
            raise EvaluationSnapshotError(
                "orders do not match the fixed evaluation seed set"
            )
        if {row["record_id"] for row in original_refunds} != set(
            REFUND_TIMESTAMPS
        ):
            raise EvaluationSnapshotError(
                "refunds do not match the fixed evaluation seed set"
            )

        _replace_timestamps(
            connection,
            table="orders",
            id_column="order_id",
            rows=_timestamp_rows(ORDER_TIMESTAMPS),
        )
        _replace_timestamps(
            connection,
            table="refunds",
            id_column="refund_id",
            rows=_timestamp_rows(REFUND_TIMESTAMPS),
        )
        connection.commit()
        yield
    finally:
        connection.rollback()
        if original_orders:
            _replace_timestamps(
                connection,
                table="orders",
                id_column="order_id",
                rows=original_orders,
            )
        if original_refunds:
            _replace_timestamps(
                connection,
                table="refunds",
                id_column="refund_id",
                rows=original_refunds,
            )
        connection.commit()
        if locked:
            connection.execute(
                "SELECT pg_advisory_unlock(%(lock_id)s)",
                {"lock_id": EVALUATION_SNAPSHOT_LOCK_ID},
            )
            connection.commit()
        connection.close()
