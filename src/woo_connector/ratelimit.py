"""Client-side rate limiting and retry policy.

WooCommerce itself ships no rate limiter, but almost every real store sits behind one
(WP Engine, Cloudflare, Kinsta, a WAF plugin...) and PHP workers are a scarce resource on
shared hosting. An agent can fire dozens of calls in a few seconds, so the connector
throttles itself and backs off politely instead of hammering the merchant's site.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime


class TokenBucket:
    """Classic token bucket: ``capacity`` tokens, refilled at ``rate`` per second.

    ``clock`` and ``sleep`` are injectable so tests can run without wall-clock waits.
    """

    def __init__(
        self,
        rate: float,
        capacity: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if rate <= 0 or capacity < 1:
            raise ValueError("rate must be > 0 and capacity >= 1")
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    async def acquire(self) -> float:
        """Take one token, sleeping until one is available. Returns the seconds waited."""
        async with self._lock:
            self._refill()
            waited = 0.0
            if self._tokens < 1:
                waited = (1 - self._tokens) / self.rate
                await self._sleep(waited)
                self._refill()
            self._tokens -= 1
            return waited


class RetryPolicy:
    """Decides whether and how long to wait before retrying a failed GET.

    * 429 / 503 with ``Retry-After`` -> wait exactly what the server asked (capped).
    * other retryable statuses / network errors -> exponential back-off with full jitter.
    Only idempotent reads go through this, so retrying is always safe.
    """

    retryable_statuses = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(
        self,
        max_retries: int = 4,
        *,
        base_delay: float = 0.5,
        max_delay: float = 20.0,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._rng = rng

    def should_retry(self, attempt: int, status: int | None) -> bool:
        """``attempt`` is zero-based: how many retries have already happened."""
        if attempt >= self.max_retries:
            return False
        return status is None or status in self.retryable_statuses

    def delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            parsed = _parse_retry_after(retry_after)
            if parsed is not None:
                return min(max(parsed, 0.0), self.max_delay)
        backoff = self.base_delay * (2**attempt)
        return min(backoff + self._rng() * self.base_delay, self.max_delay)


def _parse_retry_after(value: str) -> float | None:
    """``Retry-After`` is either delta-seconds or an HTTP-date."""
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return when.timestamp() - time.time()
