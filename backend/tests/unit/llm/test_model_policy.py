from __future__ import annotations

import pytest

from nexus.llm.application import ModelNotAllowedError, ModelPolicy


def test_model_policy_resolves_only_configured_models() -> None:
    policy = ModelPolicy.from_models([" gpt-test ", "claude-test"])

    assert policy.resolve("gpt-test") == "gpt-test"
    assert policy.resolve(" claude-test ") == "claude-test"

    with pytest.raises(ModelNotAllowedError):
        policy.resolve("unconfigured-model")


@pytest.mark.parametrize("models", [[], [""], ["   "]])
def test_model_policy_requires_non_blank_configuration(models: list[str]) -> None:
    with pytest.raises(ValueError):
        ModelPolicy.from_models(models)
