import pytest

from retail_analytics_agent.resilience import (
    RetryPolicy,
    WorkflowDeadlineExceeded,
    bounded_timeout_seconds,
    wait_before_retry,
    workflow_time_budget,
)


def test_component_timeout_is_clamped_to_workflow_budget() -> None:
    with workflow_time_budget(1):
        timeout = bounded_timeout_seconds(30)

    assert 0 < timeout <= 1


def test_retry_policy_uses_capped_exponential_backoff() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        initial_backoff_seconds=0.5,
        max_backoff_seconds=1,
        jitter_ratio=0,
    )

    assert policy.delay_before_attempt(1) == 0
    assert policy.delay_before_attempt(2) == 0.5
    assert policy.delay_before_attempt(3) == 1
    assert policy.delay_before_attempt(4) == 1


def test_retry_is_not_started_when_delay_exceeds_remaining_budget() -> None:
    with workflow_time_budget(0.01):
        with pytest.raises(
            WorkflowDeadlineExceeded,
            match="before the next retry",
        ):
            wait_before_retry(1)
