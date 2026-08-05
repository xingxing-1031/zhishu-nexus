from time import time_ns

from retail_analytics_agent.approval import (
    ApprovalAuditRecord,
    ApprovalAuditStatus,
    DatabaseApprovalAuditSink,
)
from retail_analytics_agent.audit import (
    DatabaseAuditSink,
    QueryAuditRecord,
    QueryAuditStatus,
)
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisRequest,
)
from retail_analytics_agent.request_registry import (
    DatabaseAnalysisRequestStore,
    RequestClaimStatus,
    RequestRunStatus,
)


def main() -> None:
    suffix = str(time_ns())
    query_request_id = f"W5-3-QUERY-{suffix}"
    approval_request_id = f"W5-3-APPROVAL-{suffix}"
    analysis_request_id = f"W5-3-REQUEST-{suffix}"

    query_audit = QueryAuditRecord(
        request_id=query_request_id,
        user_id="USER-001",
        original_sql="SELECT order_id FROM orders LIMIT 1",
        executed_sql="SELECT order_id FROM orders LIMIT 1",
        status=QueryAuditStatus.SUCCEEDED,
        row_count=1,
        duration_ms=1,
    )
    query_sink = DatabaseAuditSink()
    query_sink.record(query_audit)
    query_sink.record(query_audit.model_copy(update={"duration_ms": 9}))

    pending = ApprovalAuditRecord(
        request_id=approval_request_id,
        requester_id="ADMIN-001",
        access_role=AccessRole.ADMIN,
        sql="SELECT reason FROM refunds LIMIT 10",
        status=ApprovalAuditStatus.PENDING,
        reasons=("query reads sensitive columns: refunds.reason",),
    )
    approved = ApprovalAuditRecord(
        request_id=approval_request_id,
        requester_id="ADMIN-001",
        access_role=AccessRole.ADMIN,
        sql="SELECT reason FROM refunds LIMIT 10",
        status=ApprovalAuditStatus.APPROVED,
        reasons=("query reads sensitive columns: refunds.reason",),
        reviewer_id="ADMIN-REVIEWER",
    )
    approval_sink = DatabaseApprovalAuditSink()
    approval_sink.record(pending)
    approval_sink.record(pending)
    approval_sink.record(approved)
    approval_sink.record(approved)

    request = AnalysisRequest(
        request_id=analysis_request_id,
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )
    access = AccessContext(user_id="USER-001", role=AccessRole.ANALYST)
    request_store = DatabaseAnalysisRequestStore()
    first_claim = request_store.claim(request, access)
    repeated_claim = request_store.claim(request, access)
    conflicting_claim = request_store.claim(
        request.model_copy(update={"question": "查询退款金额"}),
        access,
    )
    request_store.mark(analysis_request_id, RequestRunStatus.DEGRADED)

    with connect_to_database() as connection:
        query_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM query_audit_logs
            WHERE request_id = %s;
            """,
            (query_request_id,),
        ).fetchone()["count"]
        approval_statuses = connection.execute(
            """
            SELECT status
            FROM query_approval_logs
            WHERE request_id = %s
            ORDER BY approval_audit_id;
            """,
            (approval_request_id,),
        ).fetchall()
        request_status = connection.execute(
            """
            SELECT status
            FROM analysis_request_registry
            WHERE request_id = %s;
            """,
            (analysis_request_id,),
        ).fetchone()["status"]

    if query_count != 1:
        raise AssertionError(f"query audit replay created {query_count} rows")
    if [row["status"] for row in approval_statuses] != [
        "pending",
        "approved",
    ]:
        raise AssertionError(
            f"approval audit replay was not idempotent: {approval_statuses}"
        )
    if first_claim.status is not RequestClaimStatus.NEW:
        raise AssertionError("first API request was not claimed")
    if repeated_claim.status is not RequestClaimStatus.EXISTING:
        raise AssertionError("repeated API request was not reused")
    if conflicting_claim.status is not RequestClaimStatus.CONFLICT:
        raise AssertionError("request_id conflict was not detected")
    if request_status != "degraded":
        raise AssertionError("request terminal status was not persisted")

    print(
        "W5-3 resilience verification passed: audit replays were deduplicated "
        "and API request conflicts were detected"
    )


if __name__ == "__main__":
    main()
