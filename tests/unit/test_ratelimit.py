import pytest

from woo_connector.ratelimit import RetryPolicy, TokenBucket


class FakeClock:
    """Monotonic clock that only advances when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# -- token bucket ---------------------------------------------------------------------------


async def test_burst_within_capacity_never_sleeps():
    clock = FakeClock()
    bucket = TokenBucket(rate=1.0, capacity=2, clock=clock, sleep=clock.sleep)
    assert await bucket.acquire() == 0.0
    assert await bucket.acquire() == 0.0
    assert clock.sleeps == []


async def test_exhausted_bucket_waits_for_one_token():
    clock = FakeClock()
    bucket = TokenBucket(rate=2.0, capacity=1, clock=clock, sleep=clock.sleep)
    await bucket.acquire()
    waited = await bucket.acquire()
    assert waited == pytest.approx(0.5)  # 1 token at 2 tokens/sec
    assert clock.sleeps == [pytest.approx(0.5)]


async def test_bucket_refills_over_time():
    clock = FakeClock()
    bucket = TokenBucket(rate=1.0, capacity=1, clock=clock, sleep=clock.sleep)
    await bucket.acquire()
    clock.now += 10  # plenty of idle time
    assert await bucket.acquire() == 0.0


def test_bucket_rejects_bad_config():
    with pytest.raises(ValueError):
        TokenBucket(rate=0, capacity=1)


# -- retry policy ---------------------------------------------------------------------------


def test_retry_after_seconds_is_honoured_and_capped():
    policy = RetryPolicy(max_delay=5.0, rng=lambda: 0.0)
    assert policy.delay(0, "3") == 3.0
    assert policy.delay(0, "120") == 5.0


def test_exponential_backoff_with_jitter():
    policy = RetryPolicy(base_delay=0.5, max_delay=20.0, rng=lambda: 0.5)
    assert policy.delay(0) == pytest.approx(0.5 + 0.25)
    assert policy.delay(1) == pytest.approx(1.0 + 0.25)
    assert policy.delay(2) == pytest.approx(2.0 + 0.25)
    assert policy.delay(10) == 20.0  # capped


def test_unparseable_retry_after_falls_back_to_backoff():
    policy = RetryPolicy(base_delay=1.0, rng=lambda: 0.0)
    assert policy.delay(0, "soon") == 1.0


def test_should_retry_only_retryable_statuses_within_budget():
    policy = RetryPolicy(max_retries=2)
    assert policy.should_retry(0, 429)
    assert policy.should_retry(1, 503)
    assert policy.should_retry(0, None)  # network error
    assert not policy.should_retry(2, 429)  # budget spent
    assert not policy.should_retry(0, 404)
    assert not policy.should_retry(0, 401)
