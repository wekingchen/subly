"""认证入口的单进程滑动窗口限流。"""
import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock


class SlidingWindowLimiter:
    """线程安全的内存滑动窗口；返回需要等待的秒数，None 表示本次已放行。"""

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def consume(self, key: str) -> int | None:
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return max(1, math.ceil(events[0] + self.window_seconds - now))
            events.append(now)
            return None

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


login_limiter = SlidingWindowLimiter(limit=20, window_seconds=5 * 60)
register_limiter = SlidingWindowLimiter(limit=5, window_seconds=60 * 60)
verify_email_limiter = SlidingWindowLimiter(limit=10, window_seconds=10 * 60)
