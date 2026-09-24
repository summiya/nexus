from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "nexus"
FILES_ROOT = SOURCE_ROOT / "files"
DOMAIN_ROOT = FILES_ROOT / "domain"
PORTS_ROOT = FILES_ROOT / "ports"
PERSISTENCE_FILES = (
    SOURCE_ROOT / "infrastructure" / "persistence" / "file.py",
    SOURCE_ROOT / "infrastructure" / "persistence" / "_file_queries.py",
)

FORBIDDEN_DOMAIN_IMPORTS = (
    "alembic",
    "azure",
    "boto3",
    "fastapi",
    "nexus.infrastructure",
    "pydantic",
    "sqlalchemy",
    "starlette",
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


def test_file_domain_has_no_transport_provider_or_infrastructure_dependencies() -> None:
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        imports = _imports(path)
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_DOMAIN_IMPORTS
        ), path


def test_file_ports_depend_only_on_file_contracts() -> None:
    for path in sorted(PORTS_ROOT.rglob("*.py")):
        imports = _imports(path)
        assert all(
            not module.startswith("nexus") or module.startswith("nexus.files")
            for module in imports
        ), path
        assert not any(module.startswith("sqlalchemy") for module in imports), path


def test_file_persistence_remains_native_async_sqlalchemy() -> None:
    for path in PERSISTENCE_FILES:
        imports = _imports(path)
        source = path.read_text(encoding="utf-8")

        assert "sqlalchemy.ext.asyncio" in imports, path
        assert "sqlalchemy.orm" not in imports, path
        assert "create_engine" not in source, path
        assert "asyncio.to_thread" not in source, path
