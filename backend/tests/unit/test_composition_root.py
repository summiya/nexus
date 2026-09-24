import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "nexus"


def _source_files() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def _forbidden_sync_sqlalchemy_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        names = {alias.name for alias in node.names}
        if node.module == "sqlalchemy" and "create_engine" in names:
            forbidden.add("sqlalchemy.create_engine")
        if node.module == "sqlalchemy.orm":
            forbidden.update(names & {"Session", "sessionmaker"})
    return forbidden


def _uses_asyncio_to_thread(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "asyncio"
            and any(alias.name == "to_thread" for alias in node.names)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
            and node.func.attr == "to_thread"
        ):
            return True
    return False


def test_runtime_modules_do_not_import_global_settings() -> None:
    forbidden = (
        "from nexus.config.settings import settings",
        "from nexus.config import settings",
    )

    offenders = [
        path
        for path in _source_files()
        if any(value in path.read_text(encoding="utf-8") for value in forbidden)
    ]

    assert offenders == []


def test_database_and_asgi_resources_are_not_created_at_module_import() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _source_files())

    assert "SessionLocal" not in source
    assert "app = create_app()" not in source


def test_runtime_uses_one_application_state_container() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _source_files())

    assert "app.state.container" in source
    assert "request.app.state.container" in source
    for legacy_name in (
        "settings",
        "database",
        "authentication",
        "event_publisher",
        "llm_gateway",
        "rate_limiter",
        "email_provider",
        "object_storage",
        "bootstrap_dependencies",
        "llm",
        "conversations",
        "storage",
    ):
        assert f"app.state.{legacy_name}" not in source


def test_runtime_has_no_synchronous_sqlalchemy_session_or_engine_imports() -> None:
    offenders = {
        path.relative_to(SOURCE_ROOT): _forbidden_sync_sqlalchemy_imports(path)
        for path in _source_files()
        if _forbidden_sync_sqlalchemy_imports(path)
    }

    assert offenders == {}


def test_runtime_persistence_does_not_offload_database_work_to_threads() -> None:
    persistence_root = SOURCE_ROOT / "infrastructure" / "persistence"
    offenders = [
        path.relative_to(SOURCE_ROOT)
        for path in sorted(persistence_root.rglob("*.py"))
        if _uses_asyncio_to_thread(path)
    ]

    assert offenders == []
