from __future__ import annotations

import ast
from pathlib import Path

LLM_ROOT = Path(__file__).resolve().parents[3] / "src" / "nexus" / "llm"


FORBIDDEN_FRAMEWORK_IMPORTS = (
    "anthropic",
    "azure.ai",
    "boto3",
    "fastapi",
    "google.generativeai",
    "google.genai",
    "litellm",
    "openai",
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


def _python_files(folder: str) -> list[Path]:
    return sorted((LLM_ROOT / folder).rglob("*.py"))


def _nexus_imports(path: Path) -> set[str]:
    return {module for module in _imports(path) if module.startswith("nexus")}


def _assert_no_framework_imports(path: Path) -> None:
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in _imports(path)
        for forbidden in FORBIDDEN_FRAMEWORK_IMPORTS
    ), path


def test_domain_has_no_framework_or_infrastructure_imports() -> None:
    forbidden = ("nexus.api", "nexus.config", "nexus.llm.infrastructure")

    for path in _python_files("domain"):
        _assert_no_framework_imports(path)
        assert not any(
            module.startswith(forbidden) for module in _nexus_imports(path)
        ), path


def test_ports_depend_only_on_llm_domain() -> None:
    allowed = ("nexus.llm.domain", "nexus.llm.ports")

    for path in _python_files("ports"):
        _assert_no_framework_imports(path)
        assert all(module.startswith(allowed) for module in _nexus_imports(path)), path


def test_application_depends_only_on_domain_and_ports() -> None:
    allowed = (
        "nexus.llm.application",
        "nexus.llm.domain",
        "nexus.llm.ports",
    )

    for path in _python_files("application"):
        _assert_no_framework_imports(path)
        assert all(module.startswith(allowed) for module in _nexus_imports(path)), path


def test_llm_source_has_no_service_locator_or_mutable_environment_credentials() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in LLM_ROOT.rglob("*.py")
    )

    assert "GatewayRegistry" not in source
    assert "ServiceLocator" not in source
    assert "os.environ[" not in source
    assert "import_module(" not in source
