from uuid import uuid4

from retail_analytics_agent.checkpointing import open_postgres_checkpointer
from retail_analytics_agent.models import (
    AnalysisPlan,
    AnalysisRequest,
    RetrievalEvidence,
)
from retail_analytics_agent.sql_safety import prepare_safe_sql
from retail_analytics_agent.workflow import (
    EXECUTE_SQL_NODE,
    AnalysisState,
    WorkflowNodes,
    build_analysis_graph,
    create_initial_state,
    create_thread_config,
)


def _verification_nodes() -> WorkflowNodes:
    def plan(state: AnalysisState) -> dict[str, object]:
        return {
            "plan": AnalysisPlan(
                analysis_goal="统计各渠道销售额",
                metrics=["sales_amount"],
                dimensions=["channel"],
                filters=[
                    {
                        "field": "order_status",
                        "operator": "equals",
                        "value": "paid",
                    }
                ],
                time_range={"days": 30},
                limit=10,
            ),
            "trace": ["plan"],
        }

    def retrieve(state: AnalysisState) -> dict[str, object]:
        return {
            "retrieved_context": [
                RetrievalEvidence(
                    source_id="metric.sales_amount",
                    content="sales_amount uses paid orders.amount",
                )
            ],
            "trace": ["retrieve"],
        }

    def generate_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "generated_sql": (
                "SELECT channel, SUM(amount) AS sales_amount "
                "FROM orders GROUP BY channel"
            ),
            "trace": ["generate_sql"],
        }

    def validate_sql(state: AnalysisState) -> dict[str, object]:
        sql = state["generated_sql"]
        if sql is None:
            raise AssertionError("verification SQL was not generated")
        return {
            "prepared_sql": prepare_safe_sql(sql, max_rows=10),
            "sql_valid": True,
            "sql_validation_error": None,
            "trace": ["validate_sql"],
        }

    def execute_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "query_rows": [{"channel": "jd", "sales_amount": "100.00"}],
            "execution_error": None,
            "trace": ["execute_sql"],
        }

    def summarize(state: AnalysisState) -> dict[str, object]:
        return {
            "final_answer": f"返回 {len(state['query_rows'])} 行结果",
            "trace": ["summarize"],
        }

    def fail(state: AnalysisState) -> dict[str, object]:
        return {"final_answer": "分析失败", "trace": ["fail"]}

    return WorkflowNodes(
        plan=plan,
        retrieve=retrieve,
        generate_sql=generate_sql,
        validate_sql=validate_sql,
        execute_sql=execute_sql,
        summarize=summarize,
        fail=fail,
    )


def main() -> None:
    request_id = f"W3-4-{uuid4().hex[:12]}"
    request = AnalysisRequest(
        request_id=request_id,
        user_id="W3-4-VERIFIER",
        question="最近30天各渠道销售额是多少？",
        max_rows=10,
    )
    config = create_thread_config(request_id)

    with open_postgres_checkpointer() as checkpointer:
        interrupted_graph = build_analysis_graph(
            _verification_nodes(),
            checkpointer=checkpointer,
            interrupt_before=[EXECUTE_SQL_NODE],
        )
        interrupted = interrupted_graph.invoke(
            create_initial_state(request),
            config,
        )
        if interrupted_graph.get_state(config).next != (EXECUTE_SQL_NODE,):
            raise AssertionError("workflow did not pause before execute_sql")
        if interrupted["trace"][-1] != "validate_sql":
            raise AssertionError("workflow paused at the wrong state boundary")

    with open_postgres_checkpointer() as checkpointer:
        if checkpointer.get_tuple(config) is None:
            raise AssertionError("PostgreSQL checkpoint was not persisted")

        resumed_graph = build_analysis_graph(
            _verification_nodes(),
            checkpointer=checkpointer,
        )
        resumed = resumed_graph.invoke(None, config)

    expected_trace = [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "summarize",
    ]
    if resumed["trace"] != expected_trace:
        raise AssertionError(
            "completed nodes were repeated or resume order was incorrect"
        )
    if resumed["final_answer"] != "返回 1 行结果":
        raise AssertionError("resumed workflow did not finish successfully")

    print(f"W3-4 PostgreSQL checkpoint verification passed: {request_id}")


if __name__ == "__main__":
    main()
