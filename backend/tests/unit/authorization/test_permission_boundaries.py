from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

from nexus import authorization
from nexus.authorization import PermissionChecker, PermissionCheckError

AUTHORIZATION_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "authorization"
)
PERMISSION_CONTRACT = AUTHORIZATION_ROOT / "permissions.py"
PACKAGE_ROOT = AUTHORIZATION_ROOT / "__init__.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_permission_contract_is_provider_neutral() -> None:
    imports = _imports(PERMISSION_CONTRACT)

    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imports
        for forbidden in (
            "fastapi",
            "nexus.infrastructure",
            "sqlalchemy",
            "starlette",
        )
    )


def test_authorization_package_root_does_not_eagerly_import_bootstrap() -> None:
    assert _imports(PACKAGE_ROOT) == {"nexus.authorization.permissions"}
    assert authorization.__all__ == ["PermissionCheckError", "PermissionChecker"]


def test_permission_checker_exposes_the_trusted_identity_contract() -> None:
    method = PermissionChecker.has_permission
    signature = inspect.signature(method)
    hints = get_type_hints(method)

    assert inspect.iscoroutinefunction(method)
    assert list(signature.parameters) == [
        "self",
        "organization_public_id",
        "user_public_id",
        "permission_key",
    ]
    assert hints == {
        "organization_public_id": UUID,
        "user_public_id": UUID,
        "permission_key": str,
        "return": bool,
    }
    assert issubclass(PermissionCheckError, Exception)
