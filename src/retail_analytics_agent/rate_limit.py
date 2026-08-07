from collections import defaultdict, deque
from collections.abc import Callable
from math import ceil
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    """Process-local limiter for the bounded public demo."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
    ) -> int | None:
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= limit:
                return max(1, ceil(timestamps[0] + window_seconds - now))
            timestamps.append(now)
        return None

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()
