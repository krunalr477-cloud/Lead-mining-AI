"""RBAC permission matrix (spec §17)."""

import pytest

from app.constants import Role
from app.security.rbac import PERMISSIONS, has_permission


class TestAdmin:
    def test_admin_has_wildcard(self) -> None:
        assert PERMISSIONS[Role.ADMIN] == {"*"}

    @pytest.mark.parametrize(
        "permission",
        [
            "jobs:create",
            "users:write",
            "settings:write",
            "campaigns:control",
            "anything:x",  # wildcard covers permissions that don't exist yet
        ],
    )
    def test_admin_has_everything(self, permission: str) -> None:
        assert has_permission(Role.ADMIN, permission)


class TestSalesManager:
    def test_manager_granted_jobs_create(self) -> None:
        assert has_permission(Role.SALES_MANAGER, "jobs:create")

    @pytest.mark.parametrize(
        "permission",
        ["jobs:control", "campaigns:create", "suppressions:write", "templates:write"],
    )
    def test_manager_granted_operational_writes(self, permission: str) -> None:
        assert has_permission(Role.SALES_MANAGER, permission)

    @pytest.mark.parametrize("permission", ["users:write", "settings:write", "anything:x"])
    def test_manager_denied_admin_only(self, permission: str) -> None:
        assert not has_permission(Role.SALES_MANAGER, permission)


class TestSalesExecutive:
    def test_executive_denied_jobs_create(self) -> None:
        assert not has_permission(Role.SALES_EXECUTIVE, "jobs:create")

    @pytest.mark.parametrize("permission", ["jobs:read", "contacts:read", "dashboard:read"])
    def test_executive_granted_reads(self, permission: str) -> None:
        assert has_permission(Role.SALES_EXECUTIVE, permission)

    @pytest.mark.parametrize(
        "permission",
        ["companies:write", "suppressions:write", "campaigns:control", "users:write"],
    )
    def test_executive_denied_writes(self, permission: str) -> None:
        assert not has_permission(Role.SALES_EXECUTIVE, permission)

    def test_executive_scoped_grants(self) -> None:
        assert has_permission(Role.SALES_EXECUTIVE, "contacts:write_own")
        assert has_permission(Role.SALES_EXECUTIVE, "campaigns:create_if_allowed")
        assert not has_permission(Role.SALES_EXECUTIVE, "contacts:write")
        assert not has_permission(Role.SALES_EXECUTIVE, "campaigns:create")


class TestViewer:
    @pytest.mark.parametrize(
        "permission",
        ["jobs:read", "companies:read", "contacts:read", "dashboard:read", "exports:read"],
    )
    def test_viewer_granted_reads(self, permission: str) -> None:
        assert has_permission(Role.VIEWER, permission)

    @pytest.mark.parametrize(
        "permission",
        [
            "jobs:create",
            "jobs:control",
            "companies:write",
            "contacts:write",
            "campaigns:create",
            "suppressions:write",
            "exports:create",
            "users:write",
            "templates:write",
        ],
    )
    def test_viewer_denied_all_writes(self, permission: str) -> None:
        assert not has_permission(Role.VIEWER, permission)


class TestEdgeCases:
    def test_unknown_permission_string_denied_for_non_admin(self) -> None:
        for role in (Role.SALES_MANAGER, Role.SALES_EXECUTIVE, Role.VIEWER):
            assert not has_permission(role, "nonexistent:action")

    def test_every_role_has_an_entry(self) -> None:
        assert set(PERMISSIONS) == set(Role)

    def test_non_admin_roles_do_not_hold_wildcard(self) -> None:
        for role, grants in PERMISSIONS.items():
            if role is not Role.ADMIN:
                assert "*" not in grants
