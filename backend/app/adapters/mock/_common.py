"""Shared helpers for the deterministic mock adapters.

Determinism rules (task spec):
- Discovery streams are seeded from the *job_id* so a given demo job always
  yields the same companies in the same order.
- Per-company extraction/enrichment is seeded from the *company_id* so a
  company's contacts are stable no matter which job re-processes it.
- Verifier/scorer decisions are seeded from a hash of the *email* so the same
  address always lands in the same bucket.
Every mock record carries is_demo=True.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / ".." / "seeds" / "data"
DATA_DIR = DATA_DIR.resolve()


@cache
def load_corpus(filename: str) -> object:
    """Load a committed seed JSON corpus (cached for the process lifetime)."""
    path = DATA_DIR / filename
    return json.loads(path.read_text())


def rng_from(*parts: object) -> random.Random:
    """A deterministic Random seeded from a stable digest of `parts`.

    UUIDs stringify stably, so rng_from(job_id) and rng_from(company_id, "web")
    reproduce across runs and processes (unlike hash(), which is salted).
    """
    digest = hashlib.blake2b(
        "|".join(str(p) for p in parts).encode("utf-8"), digest_size=16
    ).digest()
    return random.Random(int.from_bytes(digest, "big"))


def stable_unit(*parts: object) -> float:
    """A stable float in [0, 1) from `parts` — for threshold/bucket decisions."""
    digest = hashlib.blake2b(
        "|".join(str(p) for p in parts).encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") / float(1 << 64)


def as_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
