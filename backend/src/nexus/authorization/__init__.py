"""Provider-neutral authorization contracts for NEXUS."""

from nexus.authorization.permissions import PermissionChecker, PermissionCheckError

__all__ = ["PermissionCheckError", "PermissionChecker"]
