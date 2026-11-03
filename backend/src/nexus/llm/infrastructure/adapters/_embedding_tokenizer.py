"""Load the prepackaged standard tokenizer without a runtime download fallback."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import tiktoken

from nexus.llm.domain import LLMProviderUnavailableError

CL100K_CACHE_KEY = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"
CL100K_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
_MAX_ASSET_BYTES = 2 * 1024 * 1024
_UNAVAILABLE = "Embedding tokenizer is unavailable."


def load_embedding_tokenizer() -> tiktoken.Encoding:
    """Verify the actual cache before standard initialization; never repair assets."""
    cache = os.getenv("TIKTOKEN_CACHE_DIR")
    if not cache or not Path(cache).is_absolute():
        raise LLMProviderUnavailableError(_UNAVAILABLE)
    # LiteLLM may select this cache for chat tokenization. Verify it too before
    # initialization so either configured location is ready for ordinary cl100k use.
    locations = {cache}
    custom_cache = os.getenv("CUSTOM_TIKTOKEN_CACHE_DIR")
    if custom_cache:
        locations.add(custom_cache)
    try:
        for location in locations:
            if not Path(location).is_absolute():
                raise ValueError("Invalid tokenizer cache")
            asset = Path(location) / CL100K_CACHE_KEY
            if not asset.is_file() or asset.is_symlink():
                raise ValueError("Invalid tokenizer asset")
            with asset.open("rb") as source:
                content = source.read(_MAX_ASSET_BYTES + 1)
            if (
                len(content) > _MAX_ASSET_BYTES
                or hashlib.sha256(content).hexdigest() != CL100K_SHA256
            ):
                raise ValueError("Invalid tokenizer asset")
        return tiktoken.get_encoding("cl100k_base")
    except (OSError, ValueError):
        raise LLMProviderUnavailableError(_UNAVAILABLE) from None
