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
API_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "conversations" / "api"
)
LLM_APPLICATION_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "llm" / "application"
)
CONVERSATION_PERSISTENCE_FILES = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "nexus"
    / "infrastructure"
    / "persistence"
    / "conversation.py",
    Path(__file__).resolve().parents[3]
    / "src"
    / "nexus"
    / "infrastructure"
    / "persistence"
    / "_conversation_queries.py",
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


def _api_files() -> list[Path]:
    return sorted(API_ROOT.rglob("*.py"))


def _llm_application_files() -> list[Path]:
    return sorted(LLM_APPLICATION_ROOT.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _defined_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


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
    forbidden = (
        "anthropic",
        "azure.ai",
        "fastapi",
        "google.genai",
        "google.generativeai",
        "litellm",
        "nexus.api",
        "nexus.conversations.api",
        "nexus.infrastructure",
        "nexus.llm.infrastructure",
        "openai",
        "sqlalchemy",
        "starlette",
    )

    for path in _application_files():
        imports = _imports(path)
        assert not any(
            module == blocked or module.startswith(f"{blocked}.")
            for module in imports
            for blocked in forbidden
        ), path


def test_conversation_api_has_no_concrete_persistence_or_provider_imports() -> None:
    forbidden = (
        "anthropic",
        "azure.ai",
        "google.genai",
        "google.generativeai",
        "litellm",
        "nexus.infrastructure",
        "nexus.llm.infrastructure",
        "openai",
        "sqlalchemy",
    )

    for path in _api_files():
        imports = _imports(path)
        assert not any(
            module == blocked or module.startswith(f"{blocked}.")
            for module in imports
            for blocked in forbidden
        ), path


def test_conversation_ports_keep_one_cohesive_persistence_contract() -> None:
    prohibited_contracts = {
        "ConversationRepository",
        "GenerationRepository",
        "MessageRepository",
    }

    defined_contracts = {
        class_name for path in _port_files() for class_name in _defined_classes(path)
    }

    assert "ConversationPersistence" in defined_contracts
    assert defined_contracts.isdisjoint(prohibited_contracts)


def test_llm_application_does_not_restore_behaviorless_generation_wrappers() -> None:
    removed_wrappers = {"Generate", "Stream"}

    for path in _llm_application_files():
        assert _defined_classes(path).isdisjoint(removed_wrappers), path


def test_conversation_persistence_remains_native_async_sqlalchemy() -> None:
    for path in CONVERSATION_PERSISTENCE_FILES:
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)

        assert "sqlalchemy.ext.asyncio" in imports, path
        assert "sqlalchemy.orm" not in imports, path
        assert "asyncio.to_thread" not in source, path
