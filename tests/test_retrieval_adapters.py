from unittest.mock import Mock

import pytest

from retail_analytics_agent.models import AnalysisMetric, AnalysisPlan
from retail_analytics_agent.retrieval_adapters import (
    CatalogEvidenceAdapter,
    EvidenceRetrievalError,
    MetricCandidateEvidenceAdapter,
)
from retail_analytics_agent.workflow_tools import CatalogRetrievalTool


def _plan() -> AnalysisPlan:
    return AnalysisPlan.model_validate(
        {
            "analysis_goal": "统计各渠道销售额",
            "metrics": ["sales_amount"],
            "dimensions": ["channel"],
            "filters": [{"field": "order_status", "operator": "equals", "value": "paid"}],
            "time_range": {"days": 30},
            "sort": [{"field": "sales_amount", "direction": "descending"}],
            "limit": 10,
        }
    )


def test_catalog_adapter_returns_common_result() -> None:
    result = CatalogEvidenceAdapter().retrieve(query="渠道销售额", plan=_plan())

    assert result.candidate_metrics == (AnalysisMetric.SALES_AMOUNT,)
    assert {item.source_id for item in result.evidence} >= {
        "metric.sales_amount.v1",
        "schema.orders",
    }


def test_metric_adapter_passes_query_to_candidate_search() -> None:
    metric_retriever = Mock()
    metric_retriever.search.return_value = (AnalysisMetric.SALES_AMOUNT,)

    result = MetricCandidateEvidenceAdapter(
        metric_retriever=metric_retriever,
        catalog_retriever=CatalogRetrievalTool(),
        candidate_k=3,
    ).retrieve(query="各渠道销售额", plan=_plan())

    metric_retriever.search.assert_called_once_with("各渠道销售额", top_k=3)
    assert result.candidate_metrics == (AnalysisMetric.SALES_AMOUNT,)
    assert result.evidence


def test_metric_adapter_rejects_when_required_metric_is_not_recalled() -> None:
    metric_retriever = Mock()
    metric_retriever.search.return_value = ()
    catalog_retriever = Mock()

    with pytest.raises(EvidenceRetrievalError, match="sales_amount"):
        MetricCandidateEvidenceAdapter(
            metric_retriever=metric_retriever,
            catalog_retriever=catalog_retriever,
        ).retrieve(query="各渠道销售额", plan=_plan())

    catalog_retriever.retrieve.assert_not_called()


def test_adapters_accept_dataset_scope_kwarg_like_workflow_node() -> None:
    # workflow.create_retrieve_node 以 retrieve_with_query(query, plan, scope)
    # 调用适配器；评测适配器必须接受并透传 scope，否则检索节点 TypeError。
    scope = Mock()
    catalog_retriever = Mock()
    catalog_retriever.retrieve.return_value = []
    metric_retriever = Mock()
    metric_retriever.search.return_value = (AnalysisMetric.SALES_AMOUNT,)

    catalog_adapter = CatalogEvidenceAdapter(
        catalog_retriever=catalog_retriever
    )
    assert catalog_adapter.retrieve_with_query(
        query="渠道销售额", plan=_plan(), scope=scope
    ) == []
    catalog_retriever.retrieve.assert_called_once()
    assert catalog_retriever.retrieve.call_args.kwargs["scope"] is scope

    metric_adapter = MetricCandidateEvidenceAdapter(
        metric_retriever=metric_retriever,
        catalog_retriever=catalog_retriever,
        candidate_k=3,
    )
    assert metric_adapter.retrieve_with_query(
        query="渠道销售额", plan=_plan(), scope=None
    ) == []
    assert catalog_retriever.retrieve.call_args.kwargs["scope"] is None
