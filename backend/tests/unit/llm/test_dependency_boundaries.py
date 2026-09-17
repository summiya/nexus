from __future__ import annotations

import ast
from pathlib import Path

LLM_ROOT = Path(__file__).resolve().parents[3] / "src" / "nexus" / "llm"


def _nexus_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("nexus"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("nexus")
        ):
            imports.add(node.module)
    return imports


def _python_files(folder: str) -> list[Path]:
    return sorted((LLM_ROOT / folder).glob("*.py"))


def test_domain_has_no_framework_or_infrastructure_imports() -> None:
    forbidden = ("nexus.api", "nexus.config", "nexus.llm.infrastructure")

    for path in _python_files("domain"):
        assert not any(
            module.startswith(forbidden) for module in _nexus_imports(path)
        ), path
        assert "litellm" not in path.read_text(encoding="utf-8")


def test_ports_depend_only_on_llm_domain() -> None:
    allowed = ("nexus.llm.domain", "nexus.llm.ports")

    for path in _python_files("ports"):
        assert all(module.startswith(allowed) for module in _nexus_imports(path)), path


def test_application_depends_only_on_domain_and_ports() -> None:
    allowed = (
        "nexus.llm.application",
        "nexus.llm.domain",
        "nexus.llm.ports",
    )

    for path in _python_files("application"):
        assert all(module.startswith(allowed) for module in _nexus_imports(path)), path


def test_llm_source_has_no_service_locator_or_mutable_environment_credentials() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in LLM_ROOT.rglob("*.py")
    )

    assert "GatewayRegistry" not in source
    assert "ServiceLocator" not in source
    assert "os.environ[" not in source
    assert "import_module(" not in source
