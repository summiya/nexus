"""The shared extension/MIME admission policy for Document source formats."""

from pathlib import PurePosixPath

_MIME_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
}


def document_format(original_name: str, mime_type: str) -> str | None:
    suffix = PurePosixPath(original_name).suffix.lower()
    return suffix if mime_type.lower() in _MIME_TYPES.get(suffix, set()) else None
