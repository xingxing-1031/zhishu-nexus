from collections.abc import Callable

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from retail_analytics_agent.models import (
    AnalysisPlan,
    AnalysisRequest,
    RetrievalEvidence,
)
from retail_analytics_agent.workflow import (
    EXECUTE_SQL_NODE,
    FAIL_NODE,
    GENERATE_SQL_NODE,
    SUMMARIZE_NODE,
    AnalysisState,
    WorkflowNodes,
    build_analysis_graph,
    create_initial_state,
    create_thread_config,
    route_after_sql_execution,
    route_after_sql_validation,
)


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        request_id="REQ-001",
        user_id="USER-001",
        question="最近30天各渠道销售额是多少？",
        max_rows=100,
    )


def _base_nodes(
    *,
    validate_sql: Callable[[AnalysisState], dict[str, object]] | None = None,
    execute_sql: Callable[[AnalysisState], dict[str, object]] | None = None,
) -> WorkflowNodes:
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
                sort=[{"field": "sales_amount", "direction": "descending"}],
                limit=100,
            ),
            "trace": ["plan"],
        }

    def retrieve(state: AnalysisState) -> dict[str, object]:
        return {
            "retrieved_context": [
                RetrievalEvidence(
                    source_id="schema.orders",
                    content="orders.channel, orders.amount",
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

    def default_validate_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "sql_valid": True,
            "sql_validation_error": None,
            "trace": ["validate_sql"],
        }

    def default_execute_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "query_rows": [{"channel": "京东", "sales_amount": "100.00"}],
            "execution_error": None,
            "trace": ["execute_sql"],
        }

    def summarize(state: AnalysisState) -> dict[str, object]:
        return {
            "final_answer": f"返回 {len(state['query_rows'])} 行结果",
            "trace": ["summarize"],
        }

    def fail(state: AnalysisState) -> dict[str, object]:
        reason = state["execution_error"] or state["sql_validation_error"]
        return {
            "final_answer": f"分析失败：{reason}",
            "trace": ["fail"],
        }

    return WorkflowNodes(
        plan=plan,
        retrieve=retrieve,
        generate_sql=generate_sql,
        validate_sql=validate_sql or default_validate_sql,
        execute_sql=execute_sql or default_execute_sql,
        summarize=summarize,
        fail=fail,
    )


def test_create_initial_state_sets_request_and_workflow_defaults() -> None:
    state = create_initial_state(_request(), max_retries=3)

    assert state["request_id"] == "REQ-001"
    assert state["question"] == "最近30天各渠道销售额是多少？"
    assert state["max_rows"] == 100
    assert state["retry_count"] == 0
    assert state["max_retries"] == 3
    assert state["generated_sql"] is None
    assert state["prepared_sql"] is None
    assert state["query_rows"] == []
    assert state["trace"] == []


def test_create_initial_state_rejects_negative_max_retries() -> None:
    with pytest.raises(ValueError, match="max_retries must be non-negative"):
        create_initial_state(_request(), max_retries=-1)


def test_create_thread_config_uses_stable_workflow_identity() -> None:
    assert create_thread_config("REQ-001") == {
        "configurable": {"thread_id": "REQ-001"}
    }


def test_create_thread_config_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="thread_id must not be empty"):
        create_thread_config("   ")


def test_analysis_graph_follows_success_path() -> None:
    graph = build_analysis_graph(_base_nodes())

    result = graph.invoke(create_initial_state(_request()))

    assert result["final_answer"] == "返回 1 行结果"
    assert isinstance(result["plan"], AnalysisPlan)
    assert result["trace"] == [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "summarize",
    ]


def test_checkpoint_resume_continues_without_repeating_completed_nodes() -> None:
    checkpointer = InMemorySaver()
    graph = build_analysis_graph(
        _base_nodes(),
        checkpointer=checkpointer,
        interrupt_before=[EXECUTE_SQL_NODE],
    )
    config = create_thread_config("REQ-CHECKPOINT-001")

    interrupted = graph.invoke(create_initial_state(_request()), config)

    assert interrupted["final_answer"] is None
    assert interrupted["trace"] == [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
    ]
    assert graph.get_state(config).next == (EXECUTE_SQL_NODE,)

    resumed = graph.invoke(None, config)

    assert resumed["final_answer"] == "返回 1 行结果"
    assert resumed["trace"] == [
        "plan",
        "retrieve",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "summarize",
    ]


def test_checkpoint_threads_keep_independent_request_state() -> None:
    checkpointer = InMemorySaver()
    graph = build_analysis_graph(_base_nodes(), checkpointer=checkpointer)
    first_config = create_thread_config("REQ-THREAD-001")
    second_config = create_thread_config("REQ-THREAD-002")
    second_request = AnalysisRequest(
        request_id="REQ-002",
        user_id="USER-001",
        question="最近7天商品销量是多少？",
        max_rows=10,
    )

    graph.invoke(create_initial_state(_request()), first_config)
    graph.invoke(create_initial_state(second_request), second_config)

    first_state = graph.get_state(first_config).values
    second_state = graph.get_state(second_config).values
    assert first_state["request_id"] == "REQ-001"
    assert first_state["question"] == "最近30天各渠道销售额是多少？"
    assert second_state["request_id"] == "REQ-002"
    assert second_state["question"] == "最近7天商品销量是多少？"


def test_analysis_graph_retries_sql_then_succeeds() -> None:
    validation_attempts = 0

    def validate_sql(state: AnalysisState) -> dict[str, object]:
        nonlocal validation_attempts
        validation_attempts += 1
        if validation_attempts == 1:
            return {
                "sql_valid": False,
                "sql_validation_error": "unsafe SQL",
                "retry_count": state["retry_count"] + 1,
                "trace": ["validate_sql"],
            }
        return {
            "sql_valid": True,
            "sql_validation_error": None,
            "trace": ["validate_sql"],
        }

    graph = build_analysis_graph(_base_nodes(validate_sql=validate_sql))

    result = graph.invoke(create_initial_state(_request(), max_retries=2))

    assert result["final_answer"] == "返回 1 行结果"
    assert result["retry_count"] == 1
    assert result["trace"].count("generate_sql") == 2
    assert result["trace"].count("validate_sql") == 2


def test_analysis_graph_stops_after_validation_retries_are_exhausted() -> None:
    def validate_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "sql_valid": False,
            "sql_validation_error": "unsafe SQL",
            "retry_count": state["retry_count"] + 1,
            "trace": ["validate_sql"],
        }

    graph = build_analysis_graph(_base_nodes(validate_sql=validate_sql))

    result = graph.invoke(create_initial_state(_request(), max_retries=1))

    assert result["final_answer"] == "分析失败：unsafe SQL"
    assert result["trace"][-1] == "fail"
    assert result["trace"].count("generate_sql") == 2
    assert "execute_sql" not in result["trace"]


def test_analysis_graph_can_disable_sql_regeneration() -> None:
    def validate_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "sql_valid": False,
            "sql_validation_error": "unsafe SQL",
            "retry_count": state["retry_count"] + 1,
            "trace": ["validate_sql"],
        }

    graph = build_analysis_graph(_base_nodes(validate_sql=validate_sql))

    result = graph.invoke(create_initial_state(_request(), max_retries=0))

    assert result["trace"].count("generate_sql") == 1
    assert result["trace"][-1] == "fail"


def test_analysis_graph_routes_execution_error_to_failure() -> None:
    def execute_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "query_rows": [],
            "execution_error": "database timeout",
            "trace": ["execute_sql"],
        }

    graph = build_analysis_graph(_base_nodes(execute_sql=execute_sql))

    result = graph.invoke(create_initial_state(_request()))

    assert result["final_answer"] == "分析失败：database timeout"
    assert result["trace"][-1] == "fail"
    assert "summarize" not in result["trace"]


def test_empty_query_result_still_routes_to_summary() -> None:
    def execute_sql(state: AnalysisState) -> dict[str, object]:
        return {
            "query_rows": [],
            "execution_error": None,
            "trace": ["execute_sql"],
        }

    graph = build_analysis_graph(_base_nodes(execute_sql=execute_sql))

    result = graph.invoke(create_initial_state(_request()))

    assert result["final_answer"] == "返回 0 行结果"
    assert result["trace"][-1] == "summarize"


def test_validation_router_uses_state_instead_of_result_truthiness() -> None:
    state = create_initial_state(_request(), max_retries=1)

    state["sql_valid"] = True
    assert route_after_sql_validation(state) == EXECUTE_SQL_NODE

    state["sql_valid"] = False
    state["retry_count"] = 0
    assert route_after_sql_validation(state) == GENERATE_SQL_NODE

    state["retry_count"] = 2
    assert route_after_sql_validation(state) == FAIL_NODE


def test_execution_router_treats_empty_rows_as_success() -> None:
    state = create_initial_state(_request())
    state["query_rows"] = []
    state["execution_error"] = None

    assert route_after_sql_execution(state) == SUMMARIZE_NODE

    state["execution_error"] = "database timeout"
    assert route_after_sql_execution(state) == FAIL_NODE
