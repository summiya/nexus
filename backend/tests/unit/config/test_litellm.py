from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from nexus.config.litellm import (
    LiteLLMConfigurationError,
    require_local_litellm_metadata,
)


def test_local_metadata_guard_accepts_only_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    require_local_litellm_metadata()

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "false")
    with pytest.raises(LiteLLMConfigurationError):
        require_local_litellm_metadata()


def test_litellm_version_is_the_catalog_regression_version() -> None:
    assert version("litellm") == "1.103.0"


def test_importing_asgi_module_without_setting_does_not_import_litellm() -> None:
    source_root = Path(__file__).resolve().parents[3] / "src"
    environment = os.environ.copy()
    environment.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    environment["PYTHONPATH"] = str(source_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import nexus.main; assert 'litellm' not in sys.modules",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_metadata_lookup_fails_before_importing_litellm_when_setting_is_missing() -> (
    None
):
    source_root = Path(__file__).resolve().parents[3] / "src"
    environment = os.environ.copy()
    environment.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    environment["PYTHONPATH"] = str(source_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from nexus.infrastructure.model_providers.provider_discovery "
                "import _model_info; "
                "\ntry: _model_info('openai', 'gpt-4o-mini')\n"
                "except ValueError: pass\n"
                "else: raise AssertionError('expected configuration failure')\n"
                "assert 'litellm' not in sys.modules"
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
