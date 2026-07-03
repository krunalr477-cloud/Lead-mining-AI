"""Redis token-bucket rate limiting for providers, crawl domains, and send accounts.

One atomic Lua script implements a *multi-bucket* token bucket: it refills
every bucket from elapsed server time, and consumes tokens only if ALL
buckets can satisfy the request. A single TokenBucket passes one key; the
composite send-account limiter passes its hour and day keys together, so a
send is only debited when both windows have capacity.

State per bucket is a Redis hash {tokens, last_refill} with a TTL of twice
the full-refill time (idle buckets clean themselves up; an expired bucket
re-initialises full, which is the correct steady-state value).
"""

from __future__ import annotations

import weakref

import redis

from app.config import get_settings

__all__ = [
    "CompositeBucket",
    "TokenBucket",
    "bucket_for_domain",
    "bucket_for_provider",
    "bucket_for_send_account",
    "get_redis",
]

# KEYS[i]                      = bucket hash i (fields: tokens, last_refill)
# ARGV[1]                      = requested tokens (0 = peek: refill + report, consume nothing)
# ARGV[3i-1], ARGV[3i], ARGV[3i+1] = rate, per_seconds, burst for bucket i
# Returns {allowed 0|1, suggested_delay_seconds as string}
# (floats must be returned as strings: Lua->Redis truncates numbers to integers)
_TOKEN_BUCKET_LUA = """
redis.replicate_commands()
local requested = tonumber(ARGV[1])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

local n = #KEYS
local tokens = {}
local allowed = 1

for i = 1, n do
  local rate = tonumber(ARGV[3 * i - 1])
  local per = tonumber(ARGV[3 * i])
  local burst = tonumber(ARGV[3 * i + 1])
  local state = redis.call('HMGET', KEYS[i], 'tokens', 'last_refill')
  local tk = tonumber(state[1])
  local last = tonumber(state[2])
  if tk == nil or last == nil then
    tk = burst
    last = now
  end
  local elapsed = now - last
  if elapsed < 0 then
    elapsed = 0
  end
  tk = tk + elapsed * rate / per
  if tk > burst then
    tk = burst
  end
  tokens[i] = tk
  if tk < requested then
    allowed = 0
  end
end

local delay = 0
local need = requested
if need < 1 then
  need = 1
end
for i = 1, n do
  local rate = tonumber(ARGV[3 * i - 1])
  local per = tonumber(ARGV[3 * i])
  local burst = tonumber(ARGV[3 * i + 1])
  local tk = tokens[i]
  if allowed == 1 and requested > 0 then
    tk = tk - requested
  end
  local deficit = need - tk
  if deficit > 0 then
    local wait = deficit * per / rate
    if wait > delay then
      delay = wait
    end
  end
  redis.call('HSET', KEYS[i], 'tokens', tostring(tk), 'last_refill', tostring(now))
  local ttl = math.ceil(2 * burst * per / rate)
  if ttl < 60 then
    ttl = 60
  end
  redis.call('EXPIRE', KEYS[i], ttl)
end

return {allowed, tostring(delay)}
"""

_redis_client: redis.Redis | None = None
# Lua script registered once per client (EVALSHA with automatic EVAL fallback).
_scripts: weakref.WeakKeyDictionary[redis.Redis, object] = weakref.WeakKeyDictionary()


def get_redis() -> redis.Redis:
    """Lazily-created shared sync client from settings.redis_url."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis_client


def _script_for(client: redis.Redis):
    script = _scripts.get(client)
    if script is None:
        script = client.register_script(_TOKEN_BUCKET_LUA)
        _scripts[client] = script
    return script


def _run(client: redis.Redis, buckets: list[TokenBucket], requested: float) -> tuple[bool, float]:
    keys = [bucket.key for bucket in buckets]
    args: list[float] = [requested]
    for bucket in buckets:
        args.extend((bucket.rate, bucket.per_seconds, bucket.burst))
    allowed, delay = _script_for(client)(keys=keys, args=args)
    return bool(int(allowed)), float(delay)


class TokenBucket:
    """Token bucket: `rate` tokens per `per_seconds`, holding at most `burst`.

    Buckets start full. acquire() is atomic (single Lua call) and safe across
    processes/workers sharing the Redis instance.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        key: str,
        rate: float,
        per_seconds: float,
        burst: float | None = None,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if per_seconds <= 0:
            raise ValueError("per_seconds must be > 0")
        self.redis = redis_client
        self.key = key
        self.rate = float(rate)
        self.per_seconds = float(per_seconds)
        self.burst = float(burst) if burst is not None else float(rate)
        if self.burst <= 0:
            raise ValueError("burst must be > 0")

    def acquire(self, tokens: int = 1) -> bool:
        """Consume `tokens` if available. Returns False (nothing consumed) otherwise."""
        allowed, _ = _run(self.redis, [self], tokens)
        return allowed

    def suggested_delay(self) -> float:
        """Seconds to wait until a single-token acquire() would succeed (0.0 = now)."""
        _, delay = _run(self.redis, [self], 0)
        return delay

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TokenBucket(key={self.key!r}, rate={self.rate}/{self.per_seconds}s, "
            f"burst={self.burst})"
        )


class CompositeBucket:
    """All-or-nothing acquire across several buckets (single atomic Lua call).

    Tokens are consumed from every bucket only when every bucket can satisfy
    the request — a denied hour/day send never burns quota in either window.
    """

    def __init__(self, *buckets: TokenBucket) -> None:
        if not buckets:
            raise ValueError("CompositeBucket needs at least one bucket")
        client = buckets[0].redis
        if any(bucket.redis is not client for bucket in buckets):
            raise ValueError("All buckets in a composite must share one Redis client")
        self.buckets = list(buckets)
        self.redis = client

    def acquire(self, tokens: int = 1) -> bool:
        allowed, _ = _run(self.redis, self.buckets, tokens)
        return allowed

    def suggested_delay(self) -> float:
        """Max wait across member buckets until one token is available in all."""
        _, delay = _run(self.redis, self.buckets, 0)
        return delay

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CompositeBucket({', '.join(repr(b) for b in self.buckets)})"


def bucket_for_provider(tenant_id, provider: str, rate: float, per: float) -> TokenBucket:
    """Per-tenant provider quota, e.g. RocketReach lookups or Places calls."""
    return TokenBucket(
        get_redis(),
        key=f"rl:provider:{tenant_id}:{provider}",
        rate=rate,
        per_seconds=per,
    )


def bucket_for_domain(domain: str, delay_seconds: float) -> TokenBucket:
    """Polite crawling: 1 request per `delay_seconds` per domain (no burst)."""
    return TokenBucket(
        get_redis(),
        key=f"rl:domain:{domain.lower()}",
        rate=1,
        per_seconds=delay_seconds,
        burst=1,
    )


def bucket_for_send_account(account: str, per_hour: float, per_day: float) -> CompositeBucket:
    """Gmail send throttle: consumes one token from BOTH the hour and day
    windows, and only when both allow."""
    client = get_redis()
    return CompositeBucket(
        TokenBucket(client, key=f"rl:send:{account}:hour", rate=per_hour, per_seconds=3600),
        TokenBucket(client, key=f"rl:send:{account}:day", rate=per_day, per_seconds=86400),
    )
