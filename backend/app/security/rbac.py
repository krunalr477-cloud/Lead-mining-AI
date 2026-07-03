"""Role-based access control (spec §17).

Permissions are "resource:action" strings. Admin gets everything.
"""

from app.constants import Role

PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {"*"},
    Role.SALES_MANAGER: {
        "jobs:read",
        "jobs:create",
        "jobs:control",
        "companies:read",
        "companies:write",
        "contacts:read",
        "contacts:write",
        "validation:read",
        "validation:run",
        "sheets:read",
        "sheets:sync",
        "campaigns:read",
        "campaigns:create",
        "campaigns:control",
        "bounces:read",
        "suppressions:read",
        "suppressions:write",
        "exports:read",
        "exports:create",
        "dashboard:read",
        "audit:read",
        "hiring_signals:read",
        "templates:read",
        "templates:write",
    },
    Role.SALES_EXECUTIVE: {
        "jobs:read",
        "companies:read",
        "contacts:read",
        "contacts:write_own",
        "validation:read",
        "campaigns:read",
        "campaigns:create_if_allowed",
        "bounces:read",
        "exports:read",
        "dashboard:read",
        "hiring_signals:read",
        "templates:read",
    },
    Role.VIEWER: {
        "jobs:read",
        "companies:read",
        "contacts:read",
        "validation:read",
        "campaigns:read",
        "bounces:read",
        "dashboard:read",
        "exports:read",
        "hiring_signals:read",
        "templates:read",
    },
}


def has_permission(role: Role, permission: str) -> bool:
    grants = PERMISSIONS.get(role, set())
    return "*" in grants or permission in grants
