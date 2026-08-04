from uuid import uuid4

from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.models import AccessRole
from retail_analytics_agent.query_service import execute_safe_query
from retail_analytics_agent.sql_safety import SQLSafetyError


def _expect_rejected_query(
    connection,
    audit_sink: DatabaseAuditSink,
    *,
    request_id: str,
    sql: str,
    role: AccessRole,
) -> None:
    try:
        execute_safe_query(
            connection,
            audit_sink,
            request_id=request_id,
            user_id=f"W5-1-{role.value.upper()}",
            sql=sql,
            access_role=role,
        )
    except SQLSafetyError:
        return
    raise AssertionError(f"query was not rejected: {sql}")


def main() -> None:
    run_id = uuid4().hex[:12]
    analyst_request_id = f"W5-1-ANALYST-{run_id}"
    admin_request_id = f"W5-1-ADMIN-{run_id}"
    admin_write_request_id = f"W5-1-ADMIN-WRITE-{run_id}"
    audit_sink = DatabaseAuditSink()

    with connect_to_database() as connection:
        _expect_rejected_query(
            connection,
            audit_sink,
            request_id=analyst_request_id,
            sql="SELECT reason FROM refunds",
            role=AccessRole.ANALYST,
        )
        admin_result = execute_safe_query(
            connection,
            audit_sink,
            request_id=admin_request_id,
            user_id="W5-1-ADMIN",
            sql="SELECT reason FROM refunds ORDER BY refund_id",
            max_rows=10,
            access_role=AccessRole.ADMIN,
        )
        _expect_rejected_query(
            connection,
            audit_sink,
            request_id=admin_write_request_id,
            sql="DELETE FROM orders",
            role=AccessRole.ADMIN,
        )

    if not admin_result.rows:
        raise AssertionError("admin query returned no refund seed data")

    with connect_to_database() as connection:
        audit_rows = connection.execute(
            """
            SELECT request_id, status, row_count, reason
            FROM query_audit_logs
            WHERE request_id IN (%s, %s, %s);
            """,
            (
                analyst_request_id,
                admin_request_id,
                admin_write_request_id,
            ),
        ).fetchall()

    audits = {row["request_id"]: row for row in audit_rows}
    analyst_audit = audits[analyst_request_id]
    admin_audit = audits[admin_request_id]
    admin_write_audit = audits[admin_write_request_id]

    if analyst_audit["status"] != "rejected":
        raise AssertionError("analyst rejection audit is missing")
    if "refunds.reason" not in analyst_audit["reason"]:
        raise AssertionError("analyst rejection reason is missing")
    if admin_audit["status"] != "succeeded":
        raise AssertionError("admin success audit is missing")
    if admin_audit["row_count"] != len(admin_result.rows):
        raise AssertionError("admin row count was not audited")
    if admin_write_audit["status"] != "rejected":
        raise AssertionError("admin write rejection audit is missing")
    if "read-only SELECT" not in admin_write_audit["reason"]:
        raise AssertionError("admin write rejection reason is missing")

    print(
        "W5-1 access control verification passed: "
        f"admin read {len(admin_result.rows)} refund rows"
    )


if __name__ == "__main__":
    main()
