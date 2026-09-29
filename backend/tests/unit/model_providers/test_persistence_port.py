from __future__ import annotations

import inspect
from typing import get_type_hints

from nexus.model_providers.domain import DefaultModelSelection
from nexus.model_providers.ports import (
    ModelProviderConflictError,
    ModelProviderDeleteRestrictedError,
    ModelProviderPersistence,
    ModelProviderPersistenceError,
    ModelProviderReferenceError,
)


def test_persistence_port_exposes_only_async_configuration_operations() -> None:
    operations = {
        name
        for name, value in inspect.getmembers(
            ModelProviderPersistence,
            predicate=inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }

    assert operations == {
        "load_configuration",
        "create_provider",
        "update_provider_configuration",
        "set_provider_enabled",
        "set_provider_credential_reference",
        "record_provider_validation",
        "delete_provider",
        "create_model",
        "create_discovered_models",
        "create_manual_model",
        "update_model",
        "set_model_enabled",
        "delete_model",
        "set_default",
    }


def test_persistence_errors_are_capability_specific() -> None:
    assert issubclass(ModelProviderPersistenceError, Exception)
    assert issubclass(ModelProviderConflictError, Exception)
    assert issubclass(ModelProviderReferenceError, Exception)
    assert issubclass(ModelProviderDeleteRestrictedError, Exception)


def test_set_default_returns_the_authoritative_selection() -> None:
    hints = get_type_hints(ModelProviderPersistence.set_default)

    assert hints["return"] is DefaultModelSelection
