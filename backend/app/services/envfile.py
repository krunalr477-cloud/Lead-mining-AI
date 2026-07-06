"""Safe, allowlisted reader/writer for the repo-root ``.env`` file.

This backs the Settings → *Environment keys* screen: it lets an admin view
(masked) and update the provider API keys / OAuth secrets that the app reads at
startup, making ``.env`` the single source of truth with hot-reload.

Only keys in :data:`MANAGED_ENV_KEYS` may ever be read or written — arbitrary
environment variables are never exposed or mutated. Writes are surgical: an
existing assignment is edited *in place* (preserving surrounding comments,
blank lines, key order, and any inline ``# comment`` on the same line), a
managed key that is absent is appended under a trailing managed block, and the
whole file is replaced atomically (temp file + :func:`os.replace`).

After a successful write we clear the :func:`app.config.get_settings` LRU cache
so the running API process re-reads ``.env`` on the next ``get_settings()`` —
i.e. the change hot-reloads without a restart.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT, get_settings

__all__ = [
    "MANAGED_ENV_KEYS",
    "ManagedKey",
    "UnmanagedKeyError",
    "env_path",
    "is_secret_key",
    "managed_key",
    "read_env",
    "write_env_values",
]


@dataclass(frozen=True)
class ManagedKey:
    """One entry in the managed allowlist.

    ``group``/``label`` drive the Settings UI; ``is_secret`` decides whether the
    value is ever returned in plaintext by the list endpoint (secrets are masked
    and only revealed through the dedicated, audited reveal endpoint).
    """

    key: str
    label: str
    group: str
    is_secret: bool


# Ordered allowlist — the ONLY keys this module will read or write. Grouped for
# the Settings screen; ``is_secret=True`` marks client secrets and API keys
# (never echoed in the list/plaintext), ``False`` marks non-secret config
# (redirect URIs, tenant, model, provider, demo flag) shown in the clear.
MANAGED_ENV_KEYS: tuple[ManagedKey, ...] = (
    # --- Google ---
    ManagedKey("GOOGLE_CLIENT_ID", "Google client ID", "Google", is_secret=False),
    ManagedKey("GOOGLE_CLIENT_SECRET", "Google client secret", "Google", is_secret=True),
    ManagedKey("GOOGLE_REDIRECT_URI", "Google redirect URI", "Google", is_secret=False),
    ManagedKey("GOOGLE_MAPS_API_KEY", "Google Maps API key", "Google", is_secret=True),
    # --- Microsoft ---
    ManagedKey("MICROSOFT_CLIENT_ID", "Microsoft client ID", "Microsoft", is_secret=False),
    ManagedKey("MICROSOFT_CLIENT_SECRET", "Microsoft client secret", "Microsoft", is_secret=True),
    ManagedKey("MICROSOFT_TENANT", "Microsoft tenant", "Microsoft", is_secret=False),
    ManagedKey("MICROSOFT_REDIRECT_URI", "Microsoft redirect URI", "Microsoft", is_secret=False),
    # --- Providers ---
    ManagedKey("ROCKETREACH_API_KEY", "RocketReach API key", "Providers", is_secret=True),
    ManagedKey("MILLIONVERIFIER_API_KEY", "MillionVerifier API key", "Providers", is_secret=True),
    ManagedKey("GROQ_API_KEY", "Groq API key", "Providers", is_secret=True),
    ManagedKey("GROQ_MODEL", "Groq model", "Providers", is_secret=False),
    ManagedKey("SERP_PROVIDER", "SERP provider", "Providers", is_secret=False),
    ManagedKey("SERP_API_KEY", "SERP API key", "Providers", is_secret=True),
    # --- Runtime ---
    ManagedKey("DEMO_MODE", "Demo mode", "Runtime", is_secret=False),
)

_MANAGED_INDEX: dict[str, ManagedKey] = {k.key: k for k in MANAGED_ENV_KEYS}


class UnmanagedKeyError(ValueError):
    """Raised when a caller tries to read/write a key outside the allowlist."""


def managed_key(key: str) -> ManagedKey:
    """Return the :class:`ManagedKey` for ``key`` or raise :class:`UnmanagedKeyError`."""
    entry = _MANAGED_INDEX.get(key)
    if entry is None:
        raise UnmanagedKeyError(f"Unmanaged env key: {key!r}")
    return entry


def is_secret_key(key: str) -> bool:
    """True when ``key`` is a managed secret (client secret / API key)."""
    return managed_key(key).is_secret


def env_path() -> Path:
    """Absolute path to the repo-root ``.env`` (source of truth for settings)."""
    return REPO_ROOT / ".env"


def _split_inline_comment(value_part: str) -> tuple[str, str]:
    """Split a raw RHS into (value, trailing) preserving whitespace + ``# comment``.

    ``sk-123   # my key`` -> ("sk-123", "   # my key"). A ``#`` inside a quoted
    value is not treated as a comment. Returns the value with surrounding
    whitespace stripped and the trailing chunk (leading whitespace + comment)
    verbatim so it can be re-attached after a new value.
    """
    stripped = value_part.rstrip("\n")
    # Detect a quoted value: keep everything inside quotes intact.
    quote = ""
    if stripped[:1] in ("'", '"'):
        quote = stripped[0]
    in_quote = False
    for i, ch in enumerate(stripped):
        if quote and ch == quote:
            in_quote = not in_quote
            continue
        if ch == "#" and not in_quote:
            value = stripped[:i].rstrip()
            trailing = stripped[i:]
            # Preserve the whitespace that separated value and comment.
            gap = stripped[len(value) : len(stripped) - len(trailing)]
            return value.strip(), gap + trailing
    return stripped.strip(), ""


def _parse_line(line: str) -> tuple[str, str] | None:
    """Return (KEY, raw_rhs) for a ``KEY=...`` assignment line, else ``None``.

    Ignores comments, blanks, and ``export KEY=`` (not used in this .env).
    """
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None
    key, _, rhs = stripped.partition("=")
    key = key.strip()
    if not key or any(c.isspace() for c in key):
        return None
    return key, rhs


def read_env() -> dict[str, str]:
    """Parse the repo ``.env`` and return the current values of MANAGED keys only.

    Only allowlisted keys appear in the result; unmanaged assignments in the file
    are ignored. A managed key absent from the file is simply omitted (callers
    treat a missing key as unset).
    """
    path = env_path()
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(line)
        if parsed is None:
            continue
        key, rhs = parsed
        if key not in _MANAGED_INDEX:
            continue
        value, _trailing = _split_inline_comment(rhs)
        # Strip matching surrounding quotes for the returned value.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def _format_value(value: str) -> str:
    """Render a value for the RHS, quoting only when needed to stay parseable."""
    if value == "":
        return ""
    needs_quote = value != value.strip() or "#" in value or any(c.isspace() for c in value)
    if needs_quote and not (value[0] == value[-1] and value[0] in ("'", '"')):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def write_env_values(updates: dict[str, str]) -> dict[str, str]:
    """Update MANAGED keys in the repo ``.env`` in place, atomically; hot-reload.

    - Rejects any key outside :data:`MANAGED_ENV_KEYS` (raises
      :class:`UnmanagedKeyError`) before touching the file.
    - Edits existing assignments in place, preserving comments, order, blank
      lines, and any inline ``# comment`` on the edited line.
    - Appends managed keys not already present under a trailing managed block.
    - Writes via a temp file in the same directory + :func:`os.replace` so the
      real file is never left half-written.
    - Clears the settings cache so the running process re-reads ``.env``.

    Returns the full refreshed managed-key map (as :func:`read_env` would).
    """
    unknown = [k for k in updates if k not in _MANAGED_INDEX]
    if unknown:
        raise UnmanagedKeyError(f"Unmanaged env key(s): {', '.join(sorted(unknown))}")
    if not updates:
        # Nothing to write, but still return the current managed view.
        return read_env()

    path = env_path()
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    had_trailing_newline = original.endswith("\n") or original == ""
    lines = original.splitlines()

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        parsed = _parse_line(line)
        if parsed is None:
            new_lines.append(line)
            continue
        key, rhs = parsed
        if key in remaining:
            _old_value, trailing = _split_inline_comment(rhs)
            # Preserve leading indentation of the original assignment line.
            indent = line[: len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}{key}={_format_value(remaining.pop(key))}{trailing}")
        else:
            new_lines.append(line)

    if remaining:
        # Append any managed keys that were not already present.
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append("# --- Managed keys (added via Settings) ---")
        for mk in MANAGED_ENV_KEYS:
            if mk.key in remaining:
                new_lines.append(f"{mk.key}={_format_value(remaining.pop(mk.key))}")

    content = "\n".join(new_lines)
    if had_trailing_newline and not content.endswith("\n"):
        content += "\n"

    _atomic_write(path, content)

    # Hot-reload: the running API re-reads .env on the next get_settings().
    get_settings.cache_clear()
    get_settings()
    return read_env()


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (temp file in same dir + replace)."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Best-effort cleanup of the temp file on any failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
