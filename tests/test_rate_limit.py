from retail_analytics_agent.rate_limit import SlidingWindowRateLimiter


def test_sliding_window_limiter_allows_requests_after_window() -> None:
    current_time = 100.0
    limiter = SlidingWindowRateLimiter(lambda: current_time)

    assert limiter.consume("client", limit=2, window_seconds=60) is None
    assert limiter.consume("client", limit=2, window_seconds=60) is None
    assert limiter.consume("client", limit=2, window_seconds=60) == 60

    current_time = 160.0

    assert limiter.consume("client", limit=2, window_seconds=60) is None


def test_sliding_window_limiter_isolates_clients() -> None:
    limiter = SlidingWindowRateLimiter(lambda: 100.0)

    assert limiter.consume("client-a", limit=1, window_seconds=60) is None
    assert limiter.consume("client-a", limit=1, window_seconds=60) == 60
    assert limiter.consume("client-b", limit=1, window_seconds=60) is None
