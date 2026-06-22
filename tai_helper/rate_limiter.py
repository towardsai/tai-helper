from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    name: str
    max_requests: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit_name: str = ""
    retry_after_seconds: int = 0


class FixedWindowRateLimiter:
    def __init__(self, limits: tuple[RateLimit, ...]) -> None:
        self.limits = limits
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitResult:
        now = time.time()
        for limit in self.limits:
            events = self._events[(limit.name, key)]
            while events and now - events[0] >= limit.window_seconds:
                events.popleft()
            if len(events) >= limit.max_requests:
                retry_after = max(1, int(limit.window_seconds - (now - events[0])) + 1)
                return RateLimitResult(False, limit.name, retry_after)

        for limit in self.limits:
            self._events[(limit.name, key)].append(now)
        return RateLimitResult(True)

    def clear(self) -> None:
        self._events.clear()
