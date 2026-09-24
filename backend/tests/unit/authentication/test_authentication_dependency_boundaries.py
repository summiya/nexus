from __future__ import annotations

import ast
from pathlib import Path

AUTHENTICATION_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "authentication"
)
NEXUS_ROOT = AUTHENTICATION_ROOT.parent

FORBIDDEN_IMPORTS = (
    "fastapi",
    "redis",
    "resend",
    "sqlalchemy",
    "nexus.api",
    "nexus.infrastructure",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_authentication_core_has_no_transport_or_infrastructure_imports() -> None:
    for path in sorted(AUTHENTICATION_ROOT.glob("*.py")):
        imports = _imports(path)
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_IMPORTS
        ), path


def test_authentication_records_expose_only_public_identity_fields() -> None:
    tree = ast.parse(
        (AUTHENTICATION_ROOT / "repository.py").read_text(encoding="utf-8")
    )
    identity_fields = {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and (node.target.id == "id" or node.target.id.endswith("_id"))
    }

    assert identity_fields == {
        "organization_public_id",
        "public_id",
        "user_public_id",
    }


def test_authentication_persistence_uses_only_async_sqlalchemy_sessions() -> None:
    paths = (
        NEXUS_ROOT
        / "infrastructure"
        / "persistence"
        / "repositories"
        / "authentication.py",
        NEXUS_ROOT / "infrastructure" / "persistence" / "transaction.py",
        NEXUS_ROOT / "authorization" / "bootstrap.py",
    )

    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "from sqlalchemy.orm import Session" not in source
        assert "asyncio.to_thread" not in source
