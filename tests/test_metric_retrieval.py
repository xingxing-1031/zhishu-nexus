import pytest

from retail_analytics_agent.metric_retrieval import KeywordMetricRetriever
from retail_analytics_agent.models import AnalysisMetric


def test_keyword_retriever_matches_exact_aliases() -> None:
    retriever = KeywordMetricRetriever()

    assert retriever.search("各渠道销售额") == (
        AnalysisMetric.SALES_AMOUNT,
    )
    assert retriever.search("客单价") == (
        AnalysisMetric.AVERAGE_ORDER_VALUE,
    )


def test_keyword_retriever_returns_multiple_metrics_once() -> None:
    retriever = KeywordMetricRetriever()

    assert retriever.search("退款金额、退款笔数和退款金额") == (
        AnalysisMetric.REFUND_AMOUNT,
        AnalysisMetric.REFUND_COUNT,
    )


def test_keyword_retriever_exposes_paraphrase_limit() -> None:
    retriever = KeywordMetricRetriever()

    assert retriever.search("每张单子平均花了多少钱") == ()
    assert retriever.search("今天天气怎么样") == ()


def test_keyword_retriever_validates_top_k() -> None:
    retriever = KeywordMetricRetriever()

    with pytest.raises(ValueError, match="top_k must be between"):
        retriever.search("销售额", top_k=0)
