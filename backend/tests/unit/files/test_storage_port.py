from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, AsyncIterator
from typing import get_type_hints

import nexus.files.ports as file_ports
from nexus.files.ports.storage import (
    ObjectStorage,
    ObjectStorageAlreadyExistsError,
    ObjectStorageError,
    ObjectStorageNotFoundError,
)


def test_create_object_is_an_async_streamed_create_contract() -> None:
    parameters = inspect.signature(ObjectStorage.create_object).parameters
    type_hints = get_type_hints(ObjectStorage.create_object)

    assert inspect.iscoroutinefunction(ObjectStorage.create_object)
    assert parameters["storage_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["content"].kind is inspect.Parameter.KEYWORD_ONLY
    assert type_hints["content"] == AsyncIterable[bytes]


def test_stream_object_directly_returns_the_lazy_async_iterator_contract() -> None:
    parameters = inspect.signature(ObjectStorage.stream_object).parameters
    type_hints = get_type_hints(ObjectStorage.stream_object)

    assert not inspect.iscoroutinefunction(ObjectStorage.stream_object)
    assert parameters["storage_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert type_hints["return"] == AsyncIterator[bytes]


def test_delete_object_is_an_async_contract() -> None:
    parameters = inspect.signature(ObjectStorage.delete_object).parameters

    assert inspect.iscoroutinefunction(ObjectStorage.delete_object)
    assert parameters["storage_key"].kind is inspect.Parameter.KEYWORD_ONLY


def test_storage_specific_errors_share_the_provider_neutral_base() -> None:
    assert issubclass(ObjectStorageAlreadyExistsError, ObjectStorageError)
    assert issubclass(ObjectStorageNotFoundError, ObjectStorageError)


def test_file_ports_export_the_object_storage_contract() -> None:
    assert file_ports.ObjectStorage is ObjectStorage
    assert file_ports.ObjectStorageError is ObjectStorageError
    assert file_ports.ObjectStorageAlreadyExistsError is ObjectStorageAlreadyExistsError
    assert file_ports.ObjectStorageNotFoundError is ObjectStorageNotFoundError
