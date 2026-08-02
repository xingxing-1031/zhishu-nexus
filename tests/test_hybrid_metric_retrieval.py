from unittest.mock import Mock

import pytest

from retail_analytics_agent.hybrid_metric_retrieval import (
    HybridMetricRetriever,
    reciprocal_rank_fusion,
)
from retail_analytics_agent.models import AnalysisMetric


def test_rrf_promotes_metric_supported_by_both_rankings() -> None:
    fused = reciprocal_rank_fusion(
        (
            (AnalysisMetric.SALES_AMOUNT,),
            (
                AnalysisMetric.UNITS_SOLD,
                AnalysisMetric.SALES_AMOUNT,
                AnalysisMetric.ORDER_COUNT,
            ),
        ),
        top_k=3,
    )

    assert fused == (
        AnalysisMetric.SALES_AMOUNT,
        AnalysisMetric.UNITS_SOLD,
        AnalysisMetric.ORDER_COUNT,
    )


def test_rrf_deduplicates_repeated_items_within_one_ranking() -> None:
    fused = reciprocal_rank_fusion(
        (
            (
                AnalysisMetric.SALES_AMOUNT,
                AnalysisMetric.SALES_AMOUNT,
            ),
            (AnalysisMetric.UNITS_SOLD,),
        ),
        top_k=2,
    )

    assert fused == (
        AnalysisMetric.SALES_AMOUNT,
        AnalysisMetric.UNITS_SOLD,
    )


def test_hybrid_retriever_requests_candidates_then_fuses() -> None:
    keyword = Mock()
    keyword.search.return_value = (AnalysisMetric.SALES_AMOUNT,)
    vector = Mock()
    vector.search.return_value = (
        AnalysisMetric.UNITS_SOLD,
        AnalysisMetric.SALES_AMOUNT,
    )
    retriever = HybridMetricRetriever(
        keyword_retriever=keyword,
        vector_retriever=vector,
        candidate_k=5,
    )

    result = retriever.search("销售额", top_k=1)

    assert result == (AnalysisMetric.SALES_AMOUNT,)
    keyword.search.assert_called_once_with("销售额", top_k=5)
    vector.search.assert_called_once_with("销售额", top_k=5)


@pytest.mark.parametrize(
    ("top_k", "rrf_constant", "message"),
    [(0, 60, "top_k must be between"), (1, 0, "rrf_constant must be positive")],
)
def test_rrf_validates_limits(
    top_k: int,
    rrf_constant: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        reciprocal_rank_fusion(
            ((AnalysisMetric.SALES_AMOUNT,),),
            top_k=top_k,
            rrf_constant=rrf_constant,
        )
