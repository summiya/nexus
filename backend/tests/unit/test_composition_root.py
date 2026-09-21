from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "nexus"


def _source_files() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


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
        "llm",
        "conversations",
    ):
        assert f"app.state.{legacy_name}" not in source
