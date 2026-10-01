from __future__ import annotations

import ast
import sys
from pathlib import Path

DOMAIN_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "nexus" / "documents" / "domain"
)
PORTS_ROOT = DOMAIN_ROOT.parent / "ports"


def _imports(path: Path) -> set[str]:
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
    return imports


def test_document_domain_depends_only_on_standard_library_and_itself() -> None:
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        for module in _imports(path):
            if module == "nexus.documents.domain" or module.startswith(
                "nexus.documents.domain."
            ):
                continue
            assert module.split(".", 1)[0] in sys.stdlib_module_names, (path, module)


def test_document_ports_depend_only_on_document_contracts_and_standard_library() -> (
    None
):
    for path in sorted(PORTS_ROOT.rglob("*.py")):
        for module in _imports(path):
            if module == "nexus.documents" or module.startswith("nexus.documents."):
                continue
            assert module.split(".", 1)[0] in sys.stdlib_module_names, (path, module)
