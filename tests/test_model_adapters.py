import json

import httpx
import pytest

from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
)
from retail_analytics_agent.model_adapters import (
    ModelInvocationError,
    OllamaAnalysisPlanner,
    OllamaResultSummarizer,
    OllamaSQLGenerator,
)
from retail_analytics_agent.models import (
    AccessRole,
    AnalysisPlan,
    RetrievalEvidence,
)
from retail_analytics_agent.resilience import RetryPolicy
from retail_analytics_agent.structured_chat import StructuredChatProtocol
from retail_analytics_agent.tracing import (
    InMemoryExecutionTraceStore,
    TraceStatus,
    execution_trace_context,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        analysis_goal="统计最近 30 天各渠道销售额",
        metrics=["sales_amount"],
        dimensions=["channel"],
        time_range={"days": 30},
        sort=[{"field": "sales_amount", "direction": "descending"}],
        limit=10,
    )


def _model_plan_json() -> str:
    return json.dumps(
        {
            "analysis_goal": "统计最近 30 天各渠道销售额",
            "metrics": ["sales_amount"],
            "dimensions": ["channel"],
            "filters": [],
            "time_range_days": 30,
            "sort": [
                {"field": "sales_amount", "direction": "descending"}
            ],
            "limit": 10,
        },
        ensure_ascii=False,
    )


def _evidence() -> list[RetrievalEvidence]:
    return [
        RetrievalEvidence(
            source_id="metric.sales_amount.v1",
            content=(
                "Formula: SUM(order_items.quantity * order_items.unit_price). "
                "Fixed filters: orders.status equals paid."
            ),
        ),
        RetrievalEvidence(
            source_id="schema.join.orders.order_items",
            content="Join orders.order_id = order_items.order_id",
        ),
    ]


def test_ollama_planner_returns_validated_analysis_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3:4b"
        assert payload["think"] is False
        assert payload["format"]["properties"]["limit"]["anyOf"][0][
            "maximum"
        ] == 10
        assert payload["format"]["properties"]["filters"]["items"][
            "properties"
        ]["field"]["enum"] == [
            "channel",
            "order_status",
            "product_id",
            "category",
            "refund_status",
        ]
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload == {
            "question": "最近30天各渠道销售额是多少？",
            "max_rows": 10,
            "default_limit": 10,
            "planner_contract": {
                "supported_metrics": [
                    {
                        "metric": "sales_amount",
                        "display_name": "销售额",
                        "aliases": ["销售额", "销售金额", "成交金额"],
                        "supported_dimensions": [
                            "channel",
                            "product",
                            "category",
                            "day",
                        ],
                    },
                    {
                        "metric": "order_count",
                        "display_name": "订单数",
                        "aliases": ["订单数", "订单量"],
                        "supported_dimensions": ["channel", "day"],
                    },
                    {
                        "metric": "units_sold",
                        "display_name": "销售件数",
                        "aliases": [
                            "销售件数",
                            "销量",
                            "最好卖",
                            "最畅销",
                            "卖得最多",
                            "卖得最好",
                            "销量最高",
                        ],
                        "supported_dimensions": [
                            "channel",
                            "product",
                            "category",
                            "day",
                        ],
                    },
                    {
                        "metric": "refund_amount",
                        "display_name": "退款金额",
                        "aliases": ["退款金额"],
                        "supported_dimensions": ["channel", "refund_status", "day"],
                    },
                        {
                            "metric": "refund_count",
                            "display_name": "退款笔数",
                            "aliases": ["退款笔数", "退款单数"],
                            "supported_dimensions": ["channel", "refund_status", "day"],
                        },
                        {
                            "metric": "refund_rate",
                            "display_name": "退款率",
                            "aliases": ["退款率", "退货率", "退款占比", "refund rate"],
                            "supported_dimensions": ["channel", "day"],
                        },
                    {
                        "metric": "average_order_value",
                        "display_name": "平均订单金额",
                        "aliases": ["平均订单金额", "客单价"],
                        "supported_dimensions": ["channel", "day"],
                    },
                ],
                "supported_dimensions": [
                    "channel",
                    "product",
                    "category",
                    "order_status",
                    "refund_status",
                    "day",
                    "region",
                ],
                "explicit_metric_hints": ["sales_amount"],
                "hard_rule": (
                    "When explicit_metric_hints is not empty, metrics must contain "
                    "exactly those values and must not add unrequested metrics."
                ),
            },
            "planning_rules": [
                "Only add a dimension for an explicit grouping, comparison, or breakdown request.",
                "A status used only as a condition must not become a dimension.",
                    "Paid-order filtering for sales_amount, order_count, units_sold, refund_rate, and average_order_value is supplied by fixed metric evidence; do not duplicate order_status=paid in filters.",
                "Set limit to null unless the question explicitly requests a result count; the application will then apply default_limit.",
            ],
        }
        return httpx.Response(
            200,
            json={"message": {"content": _model_plan_json()}},
        )

    plan = OllamaAnalysisPlanner(client=_client(handler)).plan(
        "最近30天各渠道销售额是多少？",
        max_rows=10,
    )

    assert plan == _plan()


def test_openai_compatible_planner_returns_validated_analysis_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "qwen-plus"
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": _model_plan_json()}}
                ]
            },
        )

    plan = OllamaAnalysisPlanner(
        client=_client(handler),
        model="qwen-plus",
        protocol=StructuredChatProtocol.OPENAI_COMPATIBLE,
    ).plan("最近30天各渠道销售额是多少？", max_rows=10)

    assert plan == _plan()


def test_ollama_planner_applies_default_limit_and_fixed_filter_rules() -> None:
    model_output = {
        "analysis_goal": "calculate paid sales",
        "metrics": ["sales_amount"],
        "dimensions": [],
        "filters": [
            {
                "field": "order_status",
                "operator": "equals",
                "values": ["paid"],
            }
        ],
        "time_range_days": 0,
        "sort": [],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("calculate paid sales", max_rows=1000)

    assert plan.limit == 100
    assert plan.filters == []


def test_ollama_planner_applies_default_metric_sort_to_grouped_plan() -> None:
    model_output = {
        "analysis_goal": "units sold by category",
        "metrics": ["units_sold"],
        "dimensions": ["category"],
        "filters": [],
        "time_range_days": 30,
        "sort": [],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("units sold by category", max_rows=100)

    assert [item.model_dump(mode="json") for item in plan.sort] == [
        {"field": "units_sold", "direction": "descending"}
    ]


@pytest.mark.parametrize(
    ("question", "expected_metric", "expected_dimensions"),
    [
        ("返回500行订单分析结果", "order_count", []),
        ("管理员查询最多500行渠道统计", "sales_amount", ["channel"]),
    ],
)
def test_ollama_planner_aligns_generic_access_boundary_plans(
    question: str,
    expected_metric: str,
    expected_dimensions: list[str],
) -> None:
    model_output = {
        "analysis_goal": question,
        "metrics": [
            "sales_amount",
            "order_count",
            "units_sold",
            "refund_amount",
        ],
        "dimensions": ["channel", "product", "category", "day"],
        "filters": [],
        "time_range_days": 0,
        "sort": [{"field": "sales_amount", "direction": "descending"}],
        "limit": 500,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan(question, max_rows=1000)

    assert [item.value for item in plan.metrics] == [expected_metric]
    assert [item.value for item in plan.dimensions] == expected_dimensions
    assert plan.sort == []
    assert plan.limit == 500


def test_ollama_planner_aligns_explicit_metric_aliases() -> None:
    model_output = {
        "analysis_goal": "最近30天各品类销量",
        "metrics": ["sales_amount", "order_count", "units_sold"],
        "dimensions": ["category"],
        "filters": [],
        "time_range_days": 30,
        "sort": [
            {"field": "category", "direction": "ascending"},
            {"field": "day", "direction": "ascending"},
        ],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("最近30天各品类销量", max_rows=1000)

    assert plan.metrics == ["units_sold"]
    assert plan.dimensions == ["category"]
    assert [item.field.value for item in plan.sort] == ["units_sold"]


def test_ollama_planner_maps_best_seller_to_product_units() -> None:
    model_output = {
        "analysis_goal": "什么东西最好卖",
        "metrics": ["order_count"],
        "dimensions": ["category", "product"],
        "filters": [],
        "time_range_days": 0,
        "sort": [{"field": "order_count", "direction": "descending"}],
        "limit": 10,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("什么东西最好卖？", max_rows=100)

    assert [item.value for item in plan.metrics] == ["units_sold"]
    assert [item.value for item in plan.dimensions] == ["product"]
    assert [item.model_dump(mode="json") for item in plan.sort] == [
        {"field": "units_sold", "direction": "descending"}
    ]


def test_ollama_planner_removes_unrequested_status_dimension() -> None:
    model_output = {
        "analysis_goal": "统计已支付订单数",
        "metrics": ["order_count"],
        "dimensions": ["order_status"],
        "filters": [],
        "time_range_days": 0,
        "sort": [{"field": "order_status", "direction": "ascending"}],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("一共有多少个已支付订单", max_rows=100)

    assert plan.metrics == ["order_count"]
    assert plan.dimensions == []
    assert plan.sort == []


def test_ollama_planner_aligns_average_per_order_metric() -> None:
    model_output = {
        "analysis_goal": "平均每个已支付订单多少钱",
        "metrics": ["order_count"],
        "dimensions": ["order_status"],
        "filters": [],
        "time_range_days": 0,
        "sort": [],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("平均每个已支付订单多少钱", max_rows=100)

    assert plan.metrics == ["average_order_value"]
    assert plan.dimensions == []


def test_ollama_planner_adds_explicit_channel_filter() -> None:
    model_output = {
        "analysis_goal": "查询淘宝渠道销售额",
        "metrics": ["sales_amount"],
        "dimensions": ["channel"],
        "filters": [],
        "time_range_days": 0,
        "sort": [{"field": "sales_amount", "direction": "descending"}],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("只看淘宝渠道的销售额", max_rows=100)

    assert [item.model_dump(mode="json") for item in plan.filters] == [
        {"field": "channel", "operator": "equals", "value": "淘宝"}
    ]
    assert plan.sort == []


@pytest.mark.parametrize(
    ("question", "model_dimensions", "expected_dimensions"),
    [
        ("总共卖出了多少件商品", ["product"], []),
        ("不同商品类别贡献了多少销售额", ["product", "category"], ["category"]),
        ("最近30天按状态看退款金额和退款笔数", [], ["refund_status"]),
    ],
)
def test_ollama_planner_aligns_grouping_semantics(
    question: str,
    model_dimensions: list[str],
    expected_dimensions: list[str],
) -> None:
    metrics = (
        ["refund_amount", "refund_count"]
        if "退款" in question
        else ["sales_amount"]
        if "销售额" in question
        else ["units_sold"]
    )
    model_output = {
        "analysis_goal": question,
        "metrics": metrics,
        "dimensions": model_dimensions,
        "filters": [],
        "time_range_days": 30 if "30天" in question else 0,
        "sort": [],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan(question, max_rows=100)

    assert [item.value for item in plan.dimensions] == expected_dimensions


def test_ollama_planner_removes_model_placeholder_filters() -> None:
    model_output = {
        "analysis_goal": "各品类销量",
        "metrics": ["units_sold"],
        "dimensions": ["category"],
        "filters": [
            {
                "field": "category",
                "operator": "in",
                "values": ["all"],
            }
        ],
        "time_range_days": 0,
        "sort": [],
        "limit": None,
    }
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": json.dumps(model_output)}},
            )
        )
    )

    plan = planner.plan("各品类销量", max_rows=1000)

    assert plan.filters == []


def test_ollama_planner_rejects_invalid_model_output() -> None:
    planner = OllamaAnalysisPlanner(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"message": {"content": '{"metrics":["unknown"]}'}},
            )
        )
    )

    with pytest.raises(ModelInvocationError, match="invalid analysis plan"):
        planner.plan("查询销售数据", max_rows=10)


def test_ollama_sql_generator_receives_plan_evidence_and_retry_feedback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["analysis_plan"]["metrics"] == ["sales_amount"]
        assert [
            item["source_id"] for item in user_payload["retrieval_evidence"]
        ] == [
            "metric.sales_amount.v1",
            "schema.join.orders.order_items",
        ]
        contract = user_payload["sql_generation_contract"]
        assert contract["required_tables"] == []
        assert contract["required_joins"] == [
            {
                "source_id": "schema.join.orders.order_items",
                "on": "orders.order_id = order_items.order_id",
            }
        ]
        assert contract["metric_outputs"] == [
            {
                "metric": "sales_amount",
                "formula": (
                    "SUM(order_items.quantity * order_items.unit_price)"
                ),
                "output_alias": "sales_amount",
            }
        ]
        assert contract["dimension_outputs"] == [
            {
                "plan_field": "channel",
                "sql_expression": "orders.channel",
                "output_alias": "channel",
                "must_be_grouped": True,
            }
        ]
        assert contract["required_filters"] == [
            {
                "field": "order_status",
                "operator": "equals",
                "value": "paid",
            }
        ]
        assert contract["time_range"] == {
            "days": 30,
            "column": "orders.created_at",
            "predicate": (
                "orders.created_at >= %(start_time)s AND "
                "orders.created_at < %(end_time)s"
            ),
            "parameter_source": "trusted workflow reference_time",
        }
        assert user_payload["previous_validation_error"] == (
            "wildcard columns are not allowed"
        )
        assert user_payload["access_role"] == "analyst"
        assert user_payload["forbidden_columns"] == ["refunds.reason"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "sql": (
                                "SELECT o.channel, "
                                "SUM(oi.quantity * oi.unit_price) AS sales_amount "
                                "FROM orders AS o JOIN order_items AS oi "
                                "ON o.order_id = oi.order_id "
                                "WHERE o.status = 'paid' GROUP BY o.channel"
                            )
                        }
                    )
                }
            },
        )

    sql = OllamaSQLGenerator(client=_client(handler)).generate(
        question="最近30天各渠道销售额是多少？",
        plan=_plan(),
        evidence=_evidence(),
        access_role=AccessRole.ANALYST,
        validation_error="wildcard columns are not allowed",
    )

    assert "SUM(oi.quantity * oi.unit_price)" in sql
    assert "o.status = 'paid'" in sql


def test_openai_compatible_sql_generator_returns_structured_sql() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][2]["content"])
        assert user_payload["analysis_plan"]["metrics"] == ["sales_amount"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "sql": (
                                        "SELECT orders.channel AS channel, "
                                        "SUM(order_items.quantity * "
                                        "order_items.unit_price) AS sales_amount "
                                        "FROM orders JOIN order_items ON "
                                        "orders.order_id = order_items.order_id "
                                        "WHERE orders.status = 'paid' "
                                        "GROUP BY orders.channel"
                                    )
                                }
                            )
                        }
                    }
                ]
            },
        )

    sql = OllamaSQLGenerator(
        client=_client(handler),
        model="qwen-plus",
        protocol=StructuredChatProtocol.OPENAI_COMPATIBLE,
    ).generate(
        question="最近30天各渠道销售额是多少？",
        plan=_plan(),
        evidence=_evidence(),
        access_role=AccessRole.ANALYST,
    )

    assert "SUM(order_items.quantity * order_items.unit_price)" in sql


def test_sql_generation_contract_requires_product_table_and_join() -> None:
    plan = AnalysisPlan(
        analysis_goal="每种商品分别卖出了多少件",
        metrics=["units_sold"],
        dimensions=["product"],
    )
    evidence = [
        RetrievalEvidence(
            source_id="metric.units_sold.v1",
            content="SUM(order_items.quantity)",
        ),
        RetrievalEvidence(
            source_id="schema.orders",
            content="orders table",
        ),
        RetrievalEvidence(
            source_id="schema.products",
            content="products table",
        ),
        RetrievalEvidence(
            source_id="schema.order_items",
            content="order_items table",
        ),
        RetrievalEvidence(
            source_id="schema.join.orders.order_items",
            content="orders.order_id = order_items.order_id",
        ),
        RetrievalEvidence(
            source_id="schema.join.products.order_items",
            content="products.product_id = order_items.product_id",
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        contract = json.loads(payload["messages"][1]["content"])[
            "sql_generation_contract"
        ]
        assert contract["required_tables"] == [
            "order_items",
            "orders",
            "products",
        ]
        assert contract["required_joins"] == [
            {
                "source_id": "schema.join.orders.order_items",
                "on": "orders.order_id = order_items.order_id",
            },
            {
                "source_id": "schema.join.products.order_items",
                "on": "products.product_id = order_items.product_id",
            },
        ]
        assert contract["dimension_outputs"] == [
            {
                "plan_field": "product",
                "sql_expression": "products.name",
                "output_alias": "product",
                "must_be_grouped": True,
            }
        ]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "sql": (
                                "SELECT p.name AS product, "
                                "SUM(oi.quantity) AS units_sold "
                                "FROM orders o JOIN order_items oi "
                                "ON o.order_id = oi.order_id "
                                "JOIN products p ON p.product_id = oi.product_id "
                                "WHERE o.status = 'paid' GROUP BY p.name"
                            )
                        }
                    )
                }
            },
        )

    sql = OllamaSQLGenerator(client=_client(handler)).generate(
        question="每种商品分别卖出了多少件",
        plan=plan,
        evidence=evidence,
        access_role=AccessRole.ANALYST,
    )

    assert "JOIN products p" in sql


def test_ollama_sql_generator_requires_retrieval_evidence() -> None:
    generator = OllamaSQLGenerator(client=_client(lambda request: None))

    with pytest.raises(ValueError, match="retrieval evidence is required"):
        generator.generate(
            question="查询销售额",
            plan=_plan(),
            evidence=[],
            access_role=AccessRole.ANALYST,
        )


def test_ollama_summarizer_uses_real_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["query_rows"] == [
            {"channel": "jd", "sales_amount": "9000.00"}
        ]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"answer": "最近30天，京东渠道销售额为 9000.00 元。"},
                        ensure_ascii=False,
                    )
                }
            },
        )

    answer = OllamaResultSummarizer(client=_client(handler)).summarize(
        question="最近30天各渠道销售额是多少？",
        plan=_plan(),
        rows=[{"channel": "jd", "sales_amount": "9000.00"}],
    )

    assert answer == "最近30天，京东渠道销售额为 9000.00 元。"


def test_openai_compatible_summarizer_uses_verified_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": (
                                        "最近30天，京东渠道销售额为 9000.00 元。"
                                    )
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    answer = OllamaResultSummarizer(
        client=_client(handler),
        model="qwen-plus",
        protocol=StructuredChatProtocol.OPENAI_COMPATIBLE,
    ).summarize(
        question="最近30天各渠道销售额是多少？",
        plan=_plan(),
        rows=[{"channel": "jd", "sales_amount": "9000.00"}],
    )

    assert answer == "最近30天，京东渠道销售额为 9000.00 元。"


def test_ollama_summarizer_rejects_ungrounded_numbers() -> None:
    summarizer = OllamaResultSummarizer(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={
                    "message": {
                        "content": json.dumps(
                            {"answer": "京东渠道销售额为 801.00 元。"},
                            ensure_ascii=False,
                        )
                    }
                },
            )
        )
    )

    with pytest.raises(
        ModelInvocationError,
        match="absent from verified inputs: 801",
    ):
        summarizer.summarize(
            question="最近30天各渠道销售额是多少？",
            plan=_plan(),
            rows=[{"channel": "jd", "sales_amount": "800.00"}],
        )


def test_summarizer_removes_causal_claims_absent_from_query_rows() -> None:
    summarizer = OllamaResultSummarizer(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": (
                                    "淘宝退款率为12.5%，京东为10%。"
                                    "根据售后制度，可能因为平台规则宽松导致退款率较高。"
                                    "需复盘商品描述和物流时效。"
                                )
                            },
                            ensure_ascii=False,
                        )
                    }
                },
            )
        )
    )
    plan = AnalysisPlan(
        analysis_goal="按渠道统计退款率",
        metrics=["refund_rate"],
        dimensions=["channel"],
    )

    answer = summarizer.summarize(
        question="最近30天各渠道退款率为什么变化？",
        plan=plan,
        rows=[
            {"channel": "淘宝", "refund_rate": "0.125"},
            {"channel": "京东", "refund_rate": "0.10"},
        ],
    )

    assert answer == "淘宝退款率为12.5%，京东为10%。"


def test_ollama_planner_retries_transient_http_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            json={"message": {"content": _model_plan_json()}},
        )

    planner = OllamaAnalysisPlanner(
        client=_client(handler),
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
            jitter_ratio=0,
        ),
    )

    assert planner.plan("查询销售额", max_rows=10) == _plan()
    assert attempts == 2


def test_ollama_planner_does_not_retry_permanent_http_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="invalid request")

    planner = OllamaAnalysisPlanner(
        client=_client(handler),
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
            jitter_ratio=0,
        ),
    )

    with pytest.raises(ModelInvocationError, match="HTTP 400"):
        planner.plan("查询销售额", max_rows=10)

    assert attempts == 1


def test_fault_injected_model_retry_records_complete_trace() -> None:
    transport_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(
            200,
            json={"message": {"content": _model_plan_json()}},
        )

    injector = ScriptedFaultInjector(
        (
            FaultRule(
                "model.plan",
                1,
                httpx.ConnectTimeout("injected connection timeout"),
            ),
        )
    )
    trace_store = InMemoryExecutionTraceStore()
    planner = OllamaAnalysisPlanner(
        client=_client(handler),
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
            jitter_ratio=0,
        ),
    )

    with (
        execution_trace_context("REQ-TRACE", trace_store),
        fault_injection_context(injector),
    ):
        assert planner.plan("查询销售额", max_rows=10) == _plan()

    events = trace_store.list_for_request("REQ-TRACE")
    assert [(event.status, event.attempt) for event in events] == [
        (TraceStatus.STARTED, 1),
        (TraceStatus.FAILED, 1),
        (TraceStatus.RETRY_SCHEDULED, 1),
        (TraceStatus.STARTED, 2),
        (TraceStatus.SUCCEEDED, 2),
    ]
    assert events[1].error_type == "ConnectTimeout"
    assert events[2].retry_delay_ms == 0
    assert transport_calls == 1
