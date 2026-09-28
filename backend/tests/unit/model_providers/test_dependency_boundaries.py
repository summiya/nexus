from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "model_providers" / "domain"
)
PORTS_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "model_providers" / "ports"
)
APPLICATION_ROOT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "nexus"
    / "model_providers"
    / "application"
)

FORBIDDEN_IMPORTS = (
    "anthropic",
    "azure",
    "boto3",
    "cryptography",
    "fastapi",
    "google",
    "litellm",
    "openai",
    "pydantic",
    "redis",
    "sqlalchemy",
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


def test_model_provider_domain_has_no_framework_or_provider_sdk_imports() -> None:
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        imports = _imports(path)
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_IMPORTS
        ), path


def test_model_provider_domain_does_not_depend_on_llm_runtime_or_infrastructure() -> (
    None
):
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        imports = _imports(path)
        assert not any(
            module.startswith(
                (
                    "nexus.llm",
                    "nexus.api",
                    "nexus.config",
                    "nexus.infrastructure",
                )
            )
            for module in imports
        ), path


def test_model_provider_ports_have_no_framework_or_infrastructure_dependencies() -> (
    None
):
    for path in sorted(PORTS_ROOT.rglob("*.py")):
        imports = _imports(path)
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in FORBIDDEN_IMPORTS
        ), path
        assert not any(
            module.startswith(("nexus.api", "nexus.config", "nexus.infrastructure"))
            for module in imports
        ), path


def test_model_provider_application_has_no_transport_or_infrastructure_dependencies() -> (
    None
):
    for path in sorted(APPLICATION_ROOT.rglob("*.py")):
        imports = _imports(path)
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imports
            for forbidden in ("fastapi", "sqlalchemy", "azure")
        ), path
        assert not any(
            module.startswith(("nexus.api", "nexus.infrastructure"))
            for module in imports
        ), path
