"""Redis-backed provider result cache (spec §10 "cache to avoid repeated paid lookups").

Paid lookups (RocketReach person/lookup, MillionVerifier verify) are cached by a
stable key with a per-provider TTL so a re-run inside the window never spends a
second credit. Redis is used rather than a new table so no migration is required
and idle keys self-expire; the context already carries a Redis handle.

Cache misses / Redis errors degrade gracefully to "no cache" — a cache outage
must never block a lookup or crash the pipeline, it just costs a credit.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.adapters.context import SourceRunContext

__all__ = ["cache_get", "cache_set", "cache_key"]

# TTLs (seconds).
DAY = 86_400
ROCKETREACH_TTL = 90 * DAY
MILLIONVERIFIER_TTL = 30 * DAY


def cache_key(namespace: str, *parts: object) -> str:
    """A stable, collision-resistant cache key from ``parts`` under ``namespace``."""
    raw = "|".join("" if p is None else str(p).strip().lower() for p in parts)
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()
    return f"provcache:{namespace}:{digest}"


def cache_get(ctx: SourceRunContext, key: str) -> Any | None:
    """Return the decoded cached JSON value, or None on miss / any Redis error."""
    redis_client = getattr(ctx, "redis", None)
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:  # pragma: no cover - cache outage degrades to a miss
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):  # pragma: no cover - corrupt entry -> miss
        return None


def cache_set(ctx: SourceRunContext, key: str, value: Any, ttl_seconds: int) -> None:
    """Store ``value`` (JSON-encoded) under ``key`` with ``ttl_seconds`` expiry."""
    redis_client = getattr(ctx, "redis", None)
    if redis_client is None:
        return
    try:
        redis_client.setex(key, ttl_seconds, json.dumps(value))
    except Exception:  # pragma: no cover - cache outage is non-fatal
        return
