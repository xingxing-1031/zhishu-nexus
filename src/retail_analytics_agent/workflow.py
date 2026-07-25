from collections.abc import Callable
from dataclasses import dataclass
from operator import add
from typing import Annotated, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from retail_analytics_agent.models import AnalysisRequest


class AnalysisState(TypedDict):
    request_id: str
    user_id: str
    question: str
    max_rows: int
    plan: dict[str, object] | None
    retrieved_context: list[str]
    generated_sql: str | None
    sql_valid: bool | None
    sql_validation_error: str | None
    query_rows: list[dict[str, object]]
    execution_error: str | None
    final_answer: str | None
    retry_count: int
    max_retries: int
    trace: Annotated[list[str], add]


AnalysisStateUpdate = dict[str, object]
AnalysisNode = Callable[[AnalysisState], AnalysisStateUpdate]


class CompiledAnalysisGraph(Protocol):
    def invoke(self, state: AnalysisState) -> AnalysisState: ...


@dataclass(frozen=True, slots=True)
class WorkflowNodes:
    plan: AnalysisNode
    retrieve: AnalysisNode
    generate_sql: AnalysisNode
    validate_sql: AnalysisNode
    execute_sql: AnalysisNode
    summarize: AnalysisNode
    fail: AnalysisNode


PLAN_NODE = "plan"
RETRIEVE_NODE = "retrieve"
GENERATE_SQL_NODE = "generate_sql"
VALIDATE_SQL_NODE = "validate_sql"
EXECUTE_SQL_NODE = "execute_sql"
SUMMARIZE_NODE = "summarize"
FAIL_NODE = "fail"


def create_initial_state(
    request: AnalysisRequest,
    *,
    max_retries: int = 2,
) -> AnalysisState:
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    return AnalysisState(
        request_id=request.request_id,
        user_id=request.user_id,
        question=request.question,
        max_rows=request.max_rows,
        plan=None,
        retrieved_context=[],
        generated_sql=None,
        sql_valid=None,
        sql_validation_error=None,
        query_rows=[],
        execution_error=None,
        final_answer=None,
        retry_count=0,
        max_retries=max_retries,
        trace=[],
    )


def route_after_sql_validation(state: AnalysisState) -> str:
    if state["sql_valid"] is True:
        return EXECUTE_SQL_NODE
    if state["retry_count"] <= state["max_retries"]:
        return GENERATE_SQL_NODE
    return FAIL_NODE


def route_after_sql_execution(state: AnalysisState) -> str:
    if state["execution_error"] is not None:
        return FAIL_NODE
    return SUMMARIZE_NODE


def build_analysis_graph(nodes: WorkflowNodes) -> CompiledAnalysisGraph:
    graph = StateGraph(AnalysisState)

    graph.add_node(PLAN_NODE, nodes.plan)
    graph.add_node(RETRIEVE_NODE, nodes.retrieve)
    graph.add_node(GENERATE_SQL_NODE, nodes.generate_sql)
    graph.add_node(VALIDATE_SQL_NODE, nodes.validate_sql)
    graph.add_node(EXECUTE_SQL_NODE, nodes.execute_sql)
    graph.add_node(SUMMARIZE_NODE, nodes.summarize)
    graph.add_node(FAIL_NODE, nodes.fail)

    graph.add_edge(START, PLAN_NODE)
    graph.add_edge(PLAN_NODE, RETRIEVE_NODE)
    graph.add_edge(RETRIEVE_NODE, GENERATE_SQL_NODE)
    graph.add_edge(GENERATE_SQL_NODE, VALIDATE_SQL_NODE)
    graph.add_conditional_edges(
        VALIDATE_SQL_NODE,
        route_after_sql_validation,
        {
            EXECUTE_SQL_NODE: EXECUTE_SQL_NODE,
            GENERATE_SQL_NODE: GENERATE_SQL_NODE,
            FAIL_NODE: FAIL_NODE,
        },
    )
    graph.add_conditional_edges(
        EXECUTE_SQL_NODE,
        route_after_sql_execution,
        {
            SUMMARIZE_NODE: SUMMARIZE_NODE,
            FAIL_NODE: FAIL_NODE,
        },
    )
    graph.add_edge(SUMMARIZE_NODE, END)
    graph.add_edge(FAIL_NODE, END)

    return graph.compile()
