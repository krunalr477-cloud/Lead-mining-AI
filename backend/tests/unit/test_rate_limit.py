"""Token-bucket rate limiting against live Redis.

Each test uses a unique key prefix and deletes its keys afterwards, so runs
are isolated and leave Redis clean.
"""

import time
import uuid
from collections.abc import Iterator

import pytest
import redis

from app.workers.rate_limit import CompositeBucket, TokenBucket, get_redis


@pytest.fixture
def client() -> redis.Redis:
    r = get_redis()
    r.ping()  # fail fast if Redis is not running
    return r


@pytest.fixture
def key_prefix(client: redis.Redis) -> Iterator[str]:
    prefix = f"test:rl:{uuid.uuid4().hex}"
    yield prefix
    stale = list(client.scan_iter(match=f"{prefix}*"))
    if stale:
        client.delete(*stale)


class TestTokenBucket:
    def test_drain_then_deny(self, client: redis.Redis, key_prefix: str) -> None:
        bucket = TokenBucket(client, key=f"{key_prefix}:drain", rate=3, per_seconds=60, burst=3)
        assert bucket.acquire()
        assert bucket.acquire()
        assert bucket.acquire()
        assert not bucket.acquire()  # burst exhausted

    def test_denied_acquire_consumes_nothing(self, client: redis.Redis, key_prefix: str) -> None:
        bucket = TokenBucket(client, key=f"{key_prefix}:noburn", rate=2, per_seconds=60, burst=2)
        assert not bucket.acquire(tokens=3)  # more than burst: denied
        assert bucket.acquire(tokens=2)  # both tokens still there

    def test_suggested_delay(self, client: redis.Redis, key_prefix: str) -> None:
        # 1 token per 2 seconds, burst 1: after draining, next token ~2s away.
        bucket = TokenBucket(client, key=f"{key_prefix}:delay", rate=1, per_seconds=2, burst=1)
        assert bucket.suggested_delay() == 0.0  # full bucket: no wait
        assert bucket.acquire()
        delay = bucket.suggested_delay()
        assert 0.0 < delay <= 2.0

    def test_refill_after_sleep(self, client: redis.Redis, key_prefix: str) -> None:
        # 1 token per second: drained bucket refills within ~1.1s.
        bucket = TokenBucket(client, key=f"{key_prefix}:refill", rate=1, per_seconds=1, burst=1)
        assert bucket.acquire()
        assert not bucket.acquire()
        time.sleep(1.1)
        assert bucket.acquire()

    def test_refill_caps_at_burst(self, client: redis.Redis, key_prefix: str) -> None:
        # 10 tokens/sec, burst 2: even after plenty of idle time only 2 fit.
        bucket = TokenBucket(client, key=f"{key_prefix}:cap", rate=10, per_seconds=1, burst=2)
        assert bucket.acquire()
        time.sleep(0.5)
        assert bucket.acquire(tokens=2)
        assert not bucket.acquire(tokens=3)

    def test_invalid_parameters_rejected(self, client: redis.Redis, key_prefix: str) -> None:
        with pytest.raises(ValueError):
            TokenBucket(client, key=f"{key_prefix}:bad", rate=0, per_seconds=1)
        with pytest.raises(ValueError):
            TokenBucket(client, key=f"{key_prefix}:bad", rate=1, per_seconds=0)
        with pytest.raises(ValueError):
            TokenBucket(client, key=f"{key_prefix}:bad", rate=1, per_seconds=1, burst=0)


class TestCompositeBucket:
    def test_all_or_nothing(self, client: redis.Redis, key_prefix: str) -> None:
        hour = TokenBucket(client, key=f"{key_prefix}:hour", rate=2, per_seconds=3600, burst=2)
        day = TokenBucket(client, key=f"{key_prefix}:day", rate=10, per_seconds=86400, burst=10)
        composite = CompositeBucket(hour, day)

        assert composite.acquire()
        assert composite.acquire()
        # Hour window exhausted: denied, and the day bucket must NOT be debited.
        assert not composite.acquire()
        raw_tokens = client.hget(f"{key_prefix}:day", "tokens")
        assert isinstance(raw_tokens, str)  # sync client with decode_responses=True
        day_tokens = float(raw_tokens)
        assert day_tokens == pytest.approx(8.0, abs=0.01)

    def test_composite_delay_is_max_of_members(self, client: redis.Redis, key_prefix: str) -> None:
        fast = TokenBucket(client, key=f"{key_prefix}:fast", rate=1, per_seconds=1, burst=1)
        slow = TokenBucket(client, key=f"{key_prefix}:slow", rate=1, per_seconds=10, burst=1)
        composite = CompositeBucket(fast, slow)
        assert composite.acquire()
        delay = composite.suggested_delay()
        assert 5.0 < delay <= 10.0  # bounded by the slow bucket

    def test_requires_at_least_one_bucket(self) -> None:
        with pytest.raises(ValueError):
            CompositeBucket()
