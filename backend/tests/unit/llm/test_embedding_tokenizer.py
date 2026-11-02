from __future__ import annotations

import hashlib
from importlib.metadata import distribution
from pathlib import Path

import pytest
import tiktoken.load
import tiktoken.registry

from nexus.llm.domain import LLMProviderUnavailableError
from nexus.llm.infrastructure.adapters._embedding_tokenizer import (
    CL100K_CACHE_KEY,
    CL100K_SHA256,
    load_embedding_tokenizer,
)


@pytest.fixture
def tokenizer_asset(tmp_path, monkeypatch) -> Path:
    source = (
        Path(
            distribution("litellm").locate_file("litellm/litellm_core_utils/tokenizers")
        )
        / CL100K_CACHE_KEY
    )
    asset = tmp_path / CL100K_CACHE_KEY
    asset.write_bytes(source.read_bytes())
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("CUSTOM_TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})

    def forbid_download(_path):
        pytest.fail("Tokenizer attempted a runtime download")

    monkeypatch.setattr(tiktoken.load, "read_file", forbid_download)
    return asset


def test_cold_standard_tokenizer_loads_verified_cache_without_network(tokenizer_asset):
    assert hashlib.sha256(tokenizer_asset.read_bytes()).hexdigest() == CL100K_SHA256
    encoding = load_embedding_tokenizer()
    assert encoding.name == "cl100k_base"
    assert encoding.encode_ordinary("hello world") == [15339, 1917]
    assert load_embedding_tokenizer() is encoding


def test_special_token_looking_content_is_ordinary_text(tokenizer_asset):
    encoding = load_embedding_tokenizer()
    text = "document <|endoftext|> <|fim_prefix|> 日本語 café"
    tokens = encoding.encode_ordinary(text)
    assert encoding.decode(tokens) == text
    assert not set(tokens).intersection(encoding._special_tokens.values())


@pytest.mark.parametrize("cache", [None, "", "relative/cache"])
def test_unconfigured_or_relative_cache_fails_before_standard_initialization(
    monkeypatch, cache
):
    if cache is None:
        monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    else:
        monkeypatch.setenv("TIKTOKEN_CACHE_DIR", cache)
    monkeypatch.setattr(
        tiktoken,
        "get_encoding",
        lambda _name: pytest.fail("Initialization must not run"),
    )
    with pytest.raises(LLMProviderUnavailableError, match="tokenizer is unavailable"):
        load_embedding_tokenizer()


@pytest.mark.parametrize(
    "damage", ["missing", "corrupt", "oversized", "symlink", "directory"]
)
def test_missing_or_corrupt_assets_never_reach_download_capable_initialization(
    tokenizer_asset, monkeypatch, damage
):
    if damage == "corrupt":
        tokenizer_asset.write_bytes(b"corrupt vocabulary")
    elif damage == "oversized":
        tokenizer_asset.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    else:
        source = tokenizer_asset.with_name("source")
        tokenizer_asset.rename(source)
        if damage == "symlink":
            tokenizer_asset.symlink_to(source)
        elif damage == "directory":
            tokenizer_asset.mkdir()
    monkeypatch.setattr(
        tiktoken,
        "get_encoding",
        lambda _name: pytest.fail("Initialization must not run"),
    )
    with pytest.raises(LLMProviderUnavailableError) as captured:
        load_embedding_tokenizer()
    assert str(tokenizer_asset) not in str(captured.value)


@pytest.mark.parametrize(
    "cache", ["relative/cache", "/nonexistent/nexus-tokenizer-cache"]
)
def test_custom_chat_cache_must_also_be_packaged_and_verified(
    tokenizer_asset, monkeypatch, cache
):
    monkeypatch.setenv("CUSTOM_TIKTOKEN_CACHE_DIR", cache)
    monkeypatch.setattr(
        tiktoken,
        "get_encoding",
        lambda _name: pytest.fail("Initialization must not run"),
    )
    with pytest.raises(LLMProviderUnavailableError):
        load_embedding_tokenizer()


def test_valid_custom_cache_does_not_change_standard_initialization(
    tokenizer_asset, monkeypatch
):
    monkeypatch.setenv("CUSTOM_TIKTOKEN_CACHE_DIR", str(tokenizer_asset.parent))
    assert load_embedding_tokenizer().name == "cl100k_base"


@pytest.mark.parametrize(
    "error", [OSError("private path"), ValueError("private internals")]
)
def test_initialization_errors_are_safe_and_do_not_expose_details(
    tokenizer_asset, monkeypatch, error
):
    def fail(_name):
        raise error

    monkeypatch.setattr(tiktoken, "get_encoding", fail)
    with pytest.raises(LLMProviderUnavailableError) as captured:
        load_embedding_tokenizer()
    assert "private" not in str(captured.value)
