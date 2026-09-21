from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "conversations" / "domain"
)
PORTS_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "conversations" / "ports"
)
APPLICATION_ROOT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "nexus"
    / "conversations"
    / "application"
)

FORBIDDEN_IMPORTS = (
    "alembic",
    "anthropic",
    "azure.ai",
    "fastapi",
    "google.generativeai",
    "google.genai",
    "litellm",
    "nexus.api",
    "nexus.infrastructure",
    "nexus.llm",
    "openai",
    "pydantic",
    "redis",
    "sqlalchemy",
    "starlette",
)

ALLOWED_NEXUS_IMPORT = "nexus.conversations.domain"


def _python_files() -> list[Path]:
    return sorted(DOMAIN_ROOT.rglob("*.py"))


def _port_files() -> list[Path]:
    return sorted(PORTS_ROOT.rglob("*.py"))


def _application_files() -> list[Path]:
    return sorted(APPLICATION_ROOT.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_conversation_domain_has_no_infrastructure_or_transport_dependencies() -> None:
    for path in _python_files():
        imports = _imports(path)
        assert all(
            not module.startswith("nexus")
            or module == ALLOWED_NEXUS_IMPORT
            or module.startswith(f"{ALLOWED_NEXUS_IMPORT}.")
            for module in imports
        ), path
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_IMPORTS
        ), path


def test_conversation_ports_depend_only_on_conversation_contracts() -> None:
    allowed_prefixes = (
        "nexus.conversations.domain",
        "nexus.conversations.ports",
    )
    for path in _port_files():
        imports = _imports(path)
        assert all(
            not module.startswith("nexus") or module.startswith(allowed_prefixes)
            for module in imports
        ), path
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_IMPORTS
        ), path


def test_conversation_application_has_no_transport_or_infrastructure_imports() -> None:
    forbidden = ("fastapi", "litellm", "nexus.infrastructure", "sqlalchemy")

    for path in _application_files():
        imports = _imports(path)
        assert not any(
            module == blocked or module.startswith(f"{blocked}.")
            for module in imports
            for blocked in forbidden
        ), path
