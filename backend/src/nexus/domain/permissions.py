"""Stable NEXUS RBAC permission keys for implemented auth/organization capabilities."""

PERMISSION_CATALOG: dict[str, str] = {
    "users.read": "View users in the organization",
    "users.manage": "Manage users in the organization",
    "organizations.read": "View organization settings",
    "organizations.manage": "Manage organization settings",
    "roles.read": "View roles",
    "roles.manage": "Manage roles and role permissions",
    "permissions.read": "View the permission catalog",
}
