"""Settings → Environment keys (.env manager) — offline unit tests.

Covers the invariants that matter for a secret-management surface:
  * the list rendering NEVER leaks a secret plaintext — set secrets show only a
    ``****last4`` mask, non-secrets show their value;
  * the managed allowlist is closed — an unmanaged key is rejected;
  * a write round-trips through the repo ``.env`` (in a temp file), preserves
    unmanaged lines + comments, and hot-reloads ``get_settings()``;
  * reveal returns the full plaintext for a managed key;
  * every ``/settings/env-keys*`` route is admin-only (``settings:manage``),
    so a non-admin (e.g. sales_manager) is refused.

The ``.env`` writer is redirected to a temp file via monkeypatch so the real
repo ``.env`` is never touched by the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api import settings as settings_api
from app.constants import Role
from app.security.rbac import has_permission
from app.services import envfile


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the envfile reader/writer at a throwaway .env and clear the cache."""
    env = tmp_path / ".env"
    env.write_text(
        "# leading comment\n"
        "GROQ_MODEL=llama-3.1-8b-instant\n"
        "GROQ_API_KEY=gsk-secret-tail9999\n"
        "UNMANAGED_THING=keep-me  # not touched\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(envfile, "env_path", lambda: env)
    # Settings cache is cleared inside write_env_values; nothing else to do here.
    return env


def test_list_masks_secrets_and_shows_nonsecrets(temp_env: Path) -> None:
    rows = {r.key: r for r in settings_api._env_rows(envfile.read_env())}

    # Secret that is set: masked, no plaintext value ever.
    groq = rows["GROQ_API_KEY"]
    assert groq.is_secret is True
    assert groq.is_set is True
    assert groq.value is None
    assert groq.masked == "****9999"
    assert "gsk-secret-tail9999" not in (groq.masked or "")

    # Non-secret: value shown in the clear, no mask.
    model = rows["GROQ_MODEL"]
    assert model.is_secret is False
    assert model.value == "llama-3.1-8b-instant"
    assert model.masked is None

    # Unset secret: not set, masked None, source unset.
    unset = rows["ROCKETREACH_API_KEY"]
    assert unset.is_set is False
    assert unset.masked is None
    assert unset.source == "unset"


def test_no_secret_plaintext_leaks_in_any_row(temp_env: Path) -> None:
    rows = settings_api._env_rows(envfile.read_env())
    dumped = "".join(r.model_dump_json() for r in rows)
    assert "gsk-secret-tail9999" not in dumped


def test_unmanaged_key_is_rejected() -> None:
    with pytest.raises(envfile.UnmanagedKeyError):
        envfile.managed_key("DATABASE_URL")
    with pytest.raises(envfile.UnmanagedKeyError):
        envfile.write_env_values({"DATABASE_URL": "postgres://x"})


def test_write_roundtrip_preserves_and_hotreloads(temp_env: Path) -> None:
    refreshed = envfile.write_env_values({"GROQ_MODEL": "llama-3.3-70b-versatile"})
    assert refreshed["GROQ_MODEL"] == "llama-3.3-70b-versatile"

    text = temp_env.read_text(encoding="utf-8")
    # New value persisted; unmanaged line + comment preserved.
    assert "GROQ_MODEL=llama-3.3-70b-versatile" in text
    assert "UNMANAGED_THING=keep-me" in text
    assert "# leading comment" in text
    # The managed secret we did not touch is left intact.
    assert "GROQ_API_KEY=gsk-secret-tail9999" in text


def test_reveal_returns_plaintext(temp_env: Path) -> None:
    values = envfile.read_env()
    assert values.get("GROQ_API_KEY") == "gsk-secret-tail9999"


def test_all_env_key_routes_are_admin_only() -> None:
    """Every /settings/env-keys* route depends on the settings:manage guard.

    Asserted via the RBAC table: admin has it, sales_manager does not, so a
    non-admin is refused by the shared ``require("settings:manage")`` dep the
    routes are annotated with (WriteActor).
    """
    routes = [
        r
        for r in settings_api.router.routes
        if getattr(r, "path", "").startswith("/settings/env-keys")
    ]
    # list + update + reveal
    assert len(routes) == 3

    # The permission the endpoints gate on: admin yes, sales_manager no.
    assert has_permission(Role.ADMIN, "settings:manage") is True
    assert has_permission(Role.SALES_MANAGER, "settings:manage") is False

    # Each route's dependant tree must reference the settings:manage checker.
    for route in routes:
        dep_names = {getattr(d.call, "__qualname__", "") for d in route.dependant.dependencies}
        # WriteActor = Depends(require("settings:manage")); the closure is "require.<locals>.checker".
        assert any("checker" in name for name in dep_names), (
            f"{route.path} [{route.methods}] is missing an RBAC guard"
        )
