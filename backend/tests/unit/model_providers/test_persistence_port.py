from __future__ import annotations

import inspect

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
        "delete_provider",
        "create_model",
        "update_model",
        "delete_model",
        "set_default",
    }


def test_persistence_errors_are_capability_specific() -> None:
    assert issubclass(ModelProviderPersistenceError, Exception)
    assert issubclass(ModelProviderConflictError, Exception)
    assert issubclass(ModelProviderReferenceError, Exception)
    assert issubclass(ModelProviderDeleteRestrictedError, Exception)
