from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from retail_analytics_agent.business_evaluation import (
    ExpectedOutcome,
    load_business_evaluation_suite,
)
from retail_analytics_agent.database import connect_to_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = PROJECT_ROOT / "evaluation"
SUITE_PATHS = (
    EVALUATION_ROOT / "business_development.json",
    EVALUATION_ROOT / "business_holdout.json",
)
TRUSTED_OUTCOMES = {
    ExpectedOutcome.SUCCEEDED,
    ExpectedOutcome.DEGRADED,
}


FIX_SNAPSHOT_TIMESTAMPS_SQL = """
UPDATE orders AS target
SET created_at = source.created_at
FROM (
    VALUES
        ('ORD-001', TIMESTAMPTZ '2026-08-14 12:00:00+08'),
        ('ORD-002', TIMESTAMPTZ '2026-08-11 12:00:00+08'),
        ('ORD-003', TIMESTAMPTZ '2026-07-02 12:00:00+08'),
        ('ORD-004', TIMESTAMPTZ '2026-08-15 12:00:00+08'),
        ('ORD-005', TIMESTAMPTZ '2026-08-04 12:00:00+08'),
        ('ORD-006', TIMESTAMPTZ '2026-08-08 12:00:00+08'),
        ('ORD-007', TIMESTAMPTZ '2026-08-13 12:00:00+08'),
        ('ORD-008', TIMESTAMPTZ '2026-07-29 12:00:00+08'),
        ('ORD-009', TIMESTAMPTZ '2026-07-22 12:00:00+08'),
        ('ORD-010', TIMESTAMPTZ '2026-06-17 12:00:00+08')
) AS source(order_id, created_at)
WHERE target.order_id = source.order_id;

UPDATE refunds AS target
SET created_at = source.created_at
FROM (
    VALUES
        ('REF-001', TIMESTAMPTZ '2026-08-15 12:00:00+08'),
        ('REF-002', TIMESTAMPTZ '2026-08-06 12:00:00+08'),
        ('REF-003', TIMESTAMPTZ '2026-08-01 12:00:00+08'),
        ('REF-004', TIMESTAMPTZ '2026-07-07 12:00:00+08'),
        ('REF-005', TIMESTAMPTZ '2026-07-27 12:00:00+08'),
        ('REF-006', TIMESTAMPTZ '2026-08-16 00:00:00+08')
) AS source(refund_id, created_at)
WHERE target.refund_id = source.refund_id;
"""


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _normalize_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: _normalize_value(value) for key, value in row.items()}
        for row in rows
    )


def main() -> None:
    suites = tuple(load_business_evaluation_suite(path) for path in SUITE_PATHS)
    reference_times = {suite.reference_time for suite in suites}
    snapshot_ids = {suite.seed_snapshot_id for suite in suites}
    if len(reference_times) != 1 or len(snapshot_ids) != 1:
        raise AssertionError("evaluation suites do not share one fixed snapshot")
    reference_time = next(iter(reference_times))

    verified = 0
    connection = connect_to_database()
    try:
        connection.execute(FIX_SNAPSHOT_TIMESTAMPS_SQL)
        for suite in suites:
            for case in suite.cases:
                if case.expected_outcome not in TRUSTED_OUTCOMES:
                    continue
                if case.gold_sql is None or case.expected_plan is None:
                    raise AssertionError(f"missing Gold contract: {case.case_id}")

                parameters: dict[str, datetime] = {}
                if case.expected_plan.time_range is not None:
                    parameters = {
                        "start_time": reference_time
                        - timedelta(days=case.expected_plan.time_range.days),
                        "end_time": reference_time,
                    }
                rows = connection.execute(case.gold_sql, parameters).fetchall()
                actual = _normalize_rows(rows)
                if actual != case.expected_rows:
                    raise AssertionError(
                        f"Gold mismatch for {case.case_id}: "
                        f"expected={case.expected_rows!r}, actual={actual!r}"
                    )
                verified += 1
    finally:
        connection.rollback()
        connection.close()

    print(
        "W6-1 Gold verification passed: "
        f"{verified} trusted-result cases matched fixed snapshot "
        f"{next(iter(snapshot_ids))}; transaction rolled back"
    )


if __name__ == "__main__":
    main()
