from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "documents" / "domain"
)
FORBIDDEN_IMPORTS = (
    "alembic",
    "azure",
    "boto3",
    "cryptography",
    "fastapi",
    "nexus.infrastructure",
    "pgvector",
    "pydantic",
    "redis",
    "sqlalchemy",
    "starlette",
)


def test_document_domain_has_no_infrastructure_or_transport_dependencies() -> None:
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )

        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_IMPORTS
        ), path
