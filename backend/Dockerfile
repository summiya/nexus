FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/nexus/tokenizers

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY tests ./tests

RUN pip install --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

# Copy the official vocabulary already shipped in the pinned LiteLLM wheel.
# This step has no network, and no tokenizer API may repair a missing asset.
RUN --network=none python - <<'PY'
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path
import os

from nexus.llm.infrastructure.adapters._embedding_tokenizer import (
    CL100K_CACHE_KEY, CL100K_SHA256, load_embedding_tokenizer,
)

source = Path(distribution("litellm").locate_file(
    "litellm/litellm_core_utils/tokenizers"
)) / CL100K_CACHE_KEY
content = source.read_bytes()
if sha256(content).hexdigest() != CL100K_SHA256:
    raise RuntimeError("Packaged tokenizer asset failed integrity verification")
destination = Path(os.environ["TIKTOKEN_CACHE_DIR"])
destination.mkdir(parents=True, exist_ok=True)
asset = destination / CL100K_CACHE_KEY
asset.write_bytes(content)
asset.chmod(0o444)
destination.chmod(0o555)
assert load_embedding_tokenizer().encode_ordinary("offline smoke test")
PY

EXPOSE 8000

CMD ["uvicorn", "nexus.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
