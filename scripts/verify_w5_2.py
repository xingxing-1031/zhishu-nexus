from uuid import uuid4

from langgraph.types import Command

from retail_analytics_agent.approval import (
    DatabaseApprovalAuditSink,
)
from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.checkpointing import open_postgres_checkpointer
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.models import (
    AccessContext,
    AccessRole,
    AnalysisPlan,
    AnalysisRequest,
    ApprovalStatus,
    RetrievalEvidence,
)
from retail_analytics_agent.sql_safety import prepare_safe_sql
from retail_analytics_agent.workflow import (
    AnalysisState,
    WorkflowNodes,
    build_analysis_graph,
    create_approval_node,
    create_initial_state,
    create_query_risk_node,
    create_thread_config,
)
from retail_analytics_agent.workflow_tools import SafeSQLExecutionTool


def _nodes(query_connection) -> WorkflowNodes:
    audit_sink = DatabaseAuditSink()
    approval_audit_sink = DatabaseApprovalAuditSink()

    def plan(state: AnalysisState) -> dict[str, object]:
        return {
            "plan": AnalysisPlan(
                analysis_goal="读取退款原因",
                metrics=["refund_count"],
                dimensions=["refund_status"],
                limit=10,
            ),
            "trace": ["plan"],
        }

    def retrieve(state: AnalysisState) -> dict[str, object]:
        return {
            "retrieved_context": [
                RetrievalEvidence(
                    source_id="schema.refunds",
                    content="refunds.reason is sensitive and requires approval",
                )
            ],
            "trace": ["retrieve"],
        }

    def generate_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "generated_sql": "SELECT reason FROM refunds LIMIT 10",
            "trace": ["generate_sql"],
        }

    def validate_sql(state: AnalysisState) -> dict[str, object]:
        prepared = prepare_safe_sql(
            state["generated_sql"] or "",
            max_rows=10,
            access_role=state["access_role"],
        )
        return {
            "prepared_sql": prepared,
            "sql_valid": True,
            "sql_validation_error": None,
            "trace": ["validate_sql"],
        }

    def execute_sql(state: AnalysisState) -> dict[str, object]:
        result = SafeSQLExecutionTool(
            query_connection,
            audit_sink,
        ).execute(
            request_id=state["request_id"],
            user_id=state["user_id"],
            original_sql=state["generated_sql"] or "",
            prepared_sql=state["prepared_sql"],
        )
        return {
            "query_rows": result.rows,
            "execution_error": None,
            "trace": ["execute_sql"],
        }

    def summarize(state: AnalysisState) -> dict[str, object]:
        return {
            "final_answer": f"返回 {len(state['query_rows'])} 行退款原因",
            "chart_spec": None,
            "trace": ["summarize"],
        }

    def fail(state: AnalysisState) -> dict[str, object]:
        return {
            "final_answer": f"分析失败：{state['approval_reason']}",
            "trace": ["fail"],
        }

    return WorkflowNodes(
        plan=plan,
        retrieve=retrieve,
        generate_sql=generate_sql,
        validate_sql=validate_sql,
        assess_risk=create_query_risk_node(approval_audit_sink),
        request_approval=create_approval_node(approval_audit_sink),
        execute_sql=execute_sql,
        summarize=summarize,
        fail=fail,
    )


def main() -> None:
    run_id = uuid4().hex[:12]
    approved_request_id = f"W5-2-APPROVED-{run_id}"
    rejected_request_id = f"W5-2-REJECTED-{run_id}"
    admin = AccessContext(user_id="W5-2-ADMIN", role=AccessRole.ADMIN)

    approved_request = AnalysisRequest(
        request_id=approved_request_id,
        user_id=admin.user_id,
        question="读取退款原因",
        max_rows=10,
    )
    rejected_request = approved_request.model_copy(
        update={"request_id": rejected_request_id}
    )

    approved_config = create_thread_config(approved_request_id)
    rejected_config = create_thread_config(rejected_request_id)

    with open_postgres_checkpointer() as checkpointer, connect_to_database() as connection:
        graph = build_analysis_graph(
            _nodes(connection),
            checkpointer=checkpointer,
        )
        first = graph.invoke(
            create_initial_state(approved_request, access_context=admin),
            approved_config,
        )
        if first["approval_status"] is not ApprovalStatus.PENDING:
            raise AssertionError("approved request did not pause")
        if graph.get_state(approved_config).next != ("request_approval",):
            raise AssertionError("approved request paused at the wrong node")

        rejected_first = graph.invoke(
            create_initial_state(rejected_request, access_context=admin),
            rejected_config,
        )
        if rejected_first["approval_status"] is not ApprovalStatus.PENDING:
            raise AssertionError("rejected request did not pause")

    with open_postgres_checkpointer() as checkpointer, connect_to_database() as connection:
        graph = build_analysis_graph(
            _nodes(connection),
            checkpointer=checkpointer,
        )
        approved = graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "reviewer_id": "W5-2-REVIEWER",
                    "reviewer_role": "admin",
                }
            ),
            approved_config,
        )
        rejected = graph.invoke(
            Command(
                resume={
                    "decision": "reject",
                    "reason": "人工确认后拒绝本次敏感查询",
                    "reviewer_id": "W5-2-REVIEWER",
                    "reviewer_role": "admin",
                }
            ),
            rejected_config,
        )

        if approved["approval_status"] is not ApprovalStatus.APPROVED:
            raise AssertionError("approved request did not resume")
        if len(approved["query_rows"]) != 6:
            raise AssertionError("approved query returned unexpected rows")
        if rejected["approval_status"] is not ApprovalStatus.REJECTED:
            raise AssertionError("rejected request did not finish rejected")
        if "execute_sql" in rejected["trace"]:
            raise AssertionError("rejected request reached execute_sql")

    with connect_to_database() as connection:
        rows = connection.execute(
            """
            SELECT request_id, status, reviewer_id
            FROM query_approval_logs
            WHERE request_id IN (%s, %s)
            ORDER BY approval_audit_id;
            """,
            (approved_request_id, rejected_request_id),
        ).fetchall()

    statuses = [(row["request_id"], row["status"]) for row in rows]
    expected = [
        (approved_request_id, "pending"),
        (rejected_request_id, "pending"),
        (approved_request_id, "approved"),
        (rejected_request_id, "rejected"),
    ]
    if statuses != expected:
        raise AssertionError(f"unexpected approval audit events: {statuses}")
    approved_rows = [
        row for row in rows if row["status"] == "approved"
    ]
    if not approved_rows or approved_rows[0]["reviewer_id"] != "W5-2-REVIEWER":
        raise AssertionError("approval reviewer was not audited")

    print(
        "W5-2 HITL verification passed: "
        "approved query resumed after restart and rejected query did not execute"
    )


if __name__ == "__main__":
    main()
