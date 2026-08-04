import json
from uuid import uuid4

import httpx

from retail_analytics_agent.audit import DatabaseAuditSink
from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.model_adapters import (
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.models import AnalysisRequest
from retail_analytics_agent.workflow import (
    build_analysis_graph,
    create_initial_state,
    create_workflow_nodes,
)
from retail_analytics_agent.workflow_tools import (
    CatalogRetrievalTool,
    SafeSQLExecutionTool,
    SQLGlotValidationTool,
)


QUESTION = "最近30天各渠道销售额是多少？"
EXPECTED_SOURCES = {
    "metric.sales_amount.v1",
    "schema.orders",
    "schema.order_items",
    "schema.join.orders.order_items",
}


def main() -> None:
    run_id = uuid4().hex[:12]
    request = AnalysisRequest(
        request_id=f"W4-4-{run_id}",
        user_id="W4-4-VERIFIER",
        question=QUESTION,
        max_rows=10,
    )
    audit_sink = DatabaseAuditSink()

    with (
        httpx.Client(
            base_url="http://127.0.0.1:11434",
            timeout=120,
        ) as model_client,
        connect_to_database() as query_connection,
    ):
        nodes = create_workflow_nodes(
            planner=OllamaAnalysisPlanner(model_client),
            retrieval_tool=CatalogRetrievalTool(),
            sql_generator=OllamaSQLGenerator(model_client),
            validation_tool=SQLGlotValidationTool(audit_sink),
            execution_tool=SafeSQLExecutionTool(
                query_connection,
                audit_sink,
            ),
            summarizer=OllamaResultSummarizer(model_client),
        )
        result = build_analysis_graph(nodes).invoke(
            create_initial_state(request)
        )

    plan = result["plan"]
    if plan is None:
        raise AssertionError("model did not produce an analysis plan")
    if [item.value for item in plan.metrics] != ["sales_amount"]:
        raise AssertionError(f"unexpected metrics: {plan.metrics}")
    if [item.value for item in plan.dimensions] != ["channel"]:
        raise AssertionError(f"unexpected dimensions: {plan.dimensions}")
    if plan.time_range is None or plan.time_range.days != 30:
        raise AssertionError(f"unexpected time range: {plan.time_range}")

    source_ids = {item.source_id for item in result["retrieved_context"]}
    if source_ids != EXPECTED_SOURCES:
        raise AssertionError(f"unexpected retrieval evidence: {source_ids}")
    if result["execution_error"] is not None:
        raise AssertionError(result["execution_error"])
    if result["final_answer"] is None:
        raise AssertionError("model did not summarize the query result")

    output = {
        "request_id": request.request_id,
        "question": request.question,
        "plan": plan.model_dump(mode="json"),
        "evidence_source_ids": sorted(source_ids),
        "generated_sql": result["generated_sql"],
        "executed_sql": (
            result["prepared_sql"].sql
            if result["prepared_sql"] is not None
            else None
        ),
        "rows": result["query_rows"],
        "answer": result["final_answer"],
        "chart_spec": (
            result["chart_spec"].model_dump(mode="json")
            if result["chart_spec"] is not None
            else None
        ),
        "retry_count": result["retry_count"],
        "trace": result["trace"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
