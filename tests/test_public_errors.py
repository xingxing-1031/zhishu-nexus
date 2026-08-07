import pytest

from retail_analytics_agent.public_errors import public_error_message


@pytest.mark.parametrize(
    ("internal_error", "expected_message"),
    [
        (
            "metric order_count does not support dimensions: category, product",
            "当前指标不支持所选分组维度，请调整指标或分组方式。",
        ),
        (
            "Ollama model invocation failed: timeout",
            "分析服务响应超时，请稍后重试。",
        ),
        (
            "database connection refused",
            "数据服务暂时不可用，请稍后重试。",
        ),
        (
            "unexpected implementation detail",
            "分析未能完成，请调整问题后重试。",
        ),
    ],
)
def test_public_error_message_hides_internal_details(
    internal_error: str,
    expected_message: str,
) -> None:
    assert public_error_message(internal_error) == expected_message
