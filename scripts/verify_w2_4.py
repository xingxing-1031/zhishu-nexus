from uuid import uuid4

from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.query_service import execute_safe_query
from retail_analytics_agent.sql_safety import SQLSafetyError


def main() -> None:
    run_id = uuid4().hex[:12]
    success_request_id = f"W2-4-SUCCESS-{run_id}"
    rejected_request_id = f"W2-4-REJECTED-{run_id}"
    audit_sink = DatabaseAuditSink()

    with connect_to_database() as connection:
        result = execute_safe_query(
            connection,
            audit_sink,
            request_id=success_request_id,
            user_id="W2-4-VERIFIER",
            sql=(
                "SELECT channel, COUNT(*) AS order_count "
                "FROM orders GROUP BY channel "
                "ORDER BY order_count DESC"
            ),
            max_rows=10,
            statement_timeout_ms=2_000,
        )
        if not result.rows:
            raise AssertionError("safe query returned no seed data")

        try:
            execute_safe_query(
                connection,
                audit_sink,
                request_id=rejected_request_id,
                user_id="W2-4-VERIFIER",
                sql="SELECT * FROM orders",
            )
        except SQLSafetyError:
            pass
        else:
            raise AssertionError("wildcard query was not rejected")

    with connect_to_database() as connection:
        audit_rows = connection.execute(
            """
            SELECT request_id, status, row_count, executed_sql, reason
            FROM query_audit_logs
            WHERE request_id IN (%s, %s)
            ORDER BY request_id;
            """,
            (success_request_id, rejected_request_id),
        ).fetchall()

    audits = {row["request_id"]: row for row in audit_rows}
    successful = audits[success_request_id]
    rejected = audits[rejected_request_id]

    if successful["status"] != "succeeded":
        raise AssertionError("successful query audit is missing")
    if successful["row_count"] != len(result.rows):
        raise AssertionError("successful query row count was not audited")
    if not successful["executed_sql"].endswith("LIMIT 10"):
        raise AssertionError("maximum row limit was not enforced")
    if rejected["status"] != "rejected":
        raise AssertionError("rejected query audit is missing")
    if "wildcard columns are not allowed" not in rejected["reason"]:
        raise AssertionError("rejection reason was not audited")

    print("W2-4 safe query verification passed")


if __name__ == "__main__":
    main()
