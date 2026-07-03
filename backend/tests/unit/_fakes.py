"""Lightweight fakes for unit-testing real provider adapters WITHOUT a DB or Redis.

The real adapters touch the outside world only through a ``SourceRunContext``:
``audit``, ``record_usage``, and (for caching) ``redis``. We stand in a minimal
fake for each so tests stay DB-free and network-free (httpx is mocked by respx).
"""

from __future__ import annotations

from typing import Any


class FakeRedis:
    """A dict-backed stand-in for the tiny Redis surface the cache uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value


class FakeContext:
    """Records audit + usage calls; carries a FakeRedis for the provider cache."""

    def __init__(self, redis: FakeRedis | None = None) -> None:
        self.redis = redis if redis is not None else FakeRedis()
        self.audits: list[dict[str, Any]] = []
        self.usages: list[dict[str, Any]] = []

    def audit(
        self,
        url: str | None,
        status: str,
        *,
        records_found: int = 0,
        error: str | None = None,
    ) -> None:
        self.audits.append(
            {"url": url, "status": status, "records_found": records_found, "error": error}
        )

    def record_usage(
        self,
        provider: str,
        endpoint: str,
        unit_cost: float | None,
        request_count: int = 1,
    ) -> None:
        self.usages.append(
            {
                "provider": provider,
                "endpoint": endpoint,
                "unit_cost": unit_cost,
                "request_count": request_count,
            }
        )
