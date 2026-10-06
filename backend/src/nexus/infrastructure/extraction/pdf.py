"""Bounded PDF extraction in one disposable, memory-limited parser process."""

import asyncio
import json
import math
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import BinaryIO, cast

from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
)
from nexus.documents.ports.source import DocumentSource
from nexus.infrastructure.extraction.text import (
    DEFAULT_MAX_EXTRACTION_BLOCKS,
    DEFAULT_MAX_EXTRACTION_BYTES,
)

PDF_EXTRACTOR_ID = "nexus.pdf"
PDF_EXTRACTOR_VERSION = "1"
DEFAULT_MAX_PDF_PAGES = 500
DEFAULT_PDF_TIMEOUT_SECONDS = 30.0
DEFAULT_PDF_MEMORY_BYTES = 512 * 1024 * 1024
_MEMORY_LIMIT_EXIT_CODE = 2


@dataclass(frozen=True)
class PdfPageInspection:
    """Infrastructure-only native text and OCR routing signals for one page."""

    page_number: int
    texts: tuple[str, ...]
    has_raster: bool
    substantial_raster: bool
    unusable_text: bool

    @property
    def needs_ocr(self) -> bool:
        meaningful = any(
            character.isalnum() for text in self.texts for character in text
        )
        return (
            self.unusable_text
            or self.substantial_raster
            or (self.has_raster and not meaningful)
        )


class PdfDocumentExtractor:
    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_EXTRACTION_BYTES,
        max_blocks: int = DEFAULT_MAX_EXTRACTION_BLOCKS,
        max_text_bytes: int = DEFAULT_MAX_EXTRACTION_BYTES,
        max_pages: int = DEFAULT_MAX_PDF_PAGES,
        timeout_seconds: float = DEFAULT_PDF_TIMEOUT_SECONDS,
        memory_bytes: int = DEFAULT_PDF_MEMORY_BYTES,
    ) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (
                max_bytes,
                max_blocks,
                max_text_bytes,
                max_pages,
                memory_bytes,
            )
        ):
            raise ValueError("Invalid PDF extraction limits")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Invalid PDF parsing timeout")
        self._max_bytes = max_bytes
        self._max_blocks = max_blocks
        self._max_text_bytes = max_text_bytes
        self._max_pages = max_pages
        self._timeout = timeout_seconds
        self._memory_bytes = memory_bytes

    async def extract(self, source: DocumentSource) -> ExtractedDocument:
        _, parsed = await self._read_and_parse(source, inspect=False)
        return ExtractedDocument(
            source.source_file_public_id,
            source.entity_tag,
            PDF_EXTRACTOR_ID,
            PDF_EXTRACTOR_VERSION,
            tuple(cast(list[ExtractedBlock], parsed)),
        )

    @property
    def max_blocks(self) -> int:
        return self._max_blocks

    @property
    def max_text_bytes(self) -> int:
        return self._max_text_bytes

    async def inspect_source(
        self, source: DocumentSource
    ) -> tuple[bytes, list[PdfPageInspection]]:
        """Read verified EOF and inspect pages for the infrastructure OCR composite."""
        data, pages = await self._read_and_parse(source, inspect=True)
        return data, cast(list[PdfPageInspection], pages)

    async def _read_and_parse(
        self, source: DocumentSource, *, inspect: bool
    ) -> tuple[bytes, list[ExtractedBlock] | list[PdfPageInspection]]:
        if source.expected_size_bytes > self._max_bytes:
            raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
        data = bytearray()
        async for chunk in source.content:
            if len(data) + len(chunk) > self._max_bytes:
                raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
            data.extend(chunk)
        # The source has now verified normal EOF. No parser sees partial content.
        cancelled = Event()
        task = asyncio.create_task(
            asyncio.to_thread(
                _parse_in_process,
                data,
                self._max_pages,
                self._max_blocks,
                self._max_text_bytes,
                self._timeout,
                self._memory_bytes,
                cancelled,
                inspect,
            )
        )
        try:
            blocks = await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            # Retain the caller's slot until the child is killed/reaped and the
            # temporary files are removed, even after repeated cancellation.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:  # noqa: BLE001 - Cancellation remains the result.
                    break
            if not task.cancelled():
                task.exception()
            raise
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(
                DocumentExtractionFailure.PARSER_FAILURE
            ) from exc
        return bytes(data), blocks


def _parse_in_process(
    data: bytearray,
    max_pages: int,
    max_blocks: int,
    max_text_bytes: int,
    timeout_seconds: float,
    memory_bytes: int,
    cancelled: Event,
    inspect: bool = False,
) -> list[ExtractedBlock] | list[PdfPageInspection]:
    # File-backed exchange avoids pipe deadlocks and keeps all blocking work
    # (including JSON decoding) off the event loop. The directory is private.
    with tempfile.TemporaryDirectory(prefix="nexus-pdf-") as directory:
        input_path = Path(directory) / "source.pdf"
        output_path = Path(directory) / "result.json"
        input_path.write_bytes(data)
        if cancelled.is_set():
            return []
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nexus.infrastructure.extraction.pdf",
                str(input_path),
                str(output_path),
                str(max_pages),
                str(max_blocks),
                str(max_text_bytes),
                str(memory_bytes),
                "inspect" if inspect else "native",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if cancelled.is_set():
                    return []
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DocumentExtractionError(
                        DocumentExtractionFailure.RESOURCE_LIMIT
                    )
                try:
                    process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode == _MEMORY_LIMIT_EXIT_CODE:
                raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
            if process.returncode != 0:
                raise DocumentExtractionError(DocumentExtractionFailure.PARSER_FAILURE)
            # JSON escaping can expand text sixfold; block metadata is also bounded.
            if (
                output_path.stat().st_size
                > max_text_bytes * 6 + max_blocks * 64 + max_pages * 256 + 1024
            ):
                raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            if "failure" in result:
                raise DocumentExtractionError(
                    DocumentExtractionFailure(result["failure"])
                )
            if inspect:
                return [
                    PdfPageInspection(
                        number, tuple(texts), raster, substantial, unusable
                    )
                    for number, texts, raster, substantial, unusable in result["pages"]
                ]
            return [
                ExtractedBlock(
                    index, ExtractedBlockKind.PARAGRAPH, text, page_number=page
                )
                for index, (text, page) in enumerate(result["blocks"])
            ]
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def _parse_pdf(
    source: BinaryIO, max_pages: int, max_blocks: int, max_text_bytes: int
) -> list[tuple[str, int]]:
    pages = _inspect_pdf(source, max_pages, max_blocks, max_text_bytes)
    blocks = [(text, page.page_number) for page in pages for text in page.texts]
    if not blocks:
        raise DocumentExtractionError(DocumentExtractionFailure.EMPTY)
    return blocks


def _inspect_pdf(
    source: BinaryIO, max_pages: int, max_blocks: int, max_text_bytes: int
) -> list[PdfPageInspection]:
    # These imports occur only after the child has installed its memory limit.
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTContainer, LTImage, LTTextBox
    from pdfminer.pdfdocument import PDFDocument, PDFEncryptionError
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser, PDFSyntaxError
    from pdfminer.psparser import PSEOF

    try:
        if not source.read(8).startswith(b"%PDF-"):
            raise DocumentExtractionError(DocumentExtractionFailure.MALFORMED)
        source.seek(0, 2)
        source.seek(max(0, source.tell() - 1024))
        if not source.read().rstrip().endswith(b"%%EOF"):
            raise DocumentExtractionError(DocumentExtractionFailure.MALFORMED)
        source.seek(0)
        document = PDFDocument(PDFParser(source), caching=False)
        if document.encryption is not None:
            raise DocumentExtractionError(DocumentExtractionFailure.ENCRYPTED)
        resources = PDFResourceManager(caching=False)
        device = PDFPageAggregator(resources, laparams=LAParams())
        interpreter = PDFPageInterpreter(resources, device)
        pages: list[PdfPageInspection] = []
        block_count = 0
        text_bytes = 0
        try:
            for page_number, page in enumerate(PDFPage.create_pages(document), start=1):
                if page_number > max_pages:
                    raise DocumentExtractionError(
                        DocumentExtractionFailure.RESOURCE_LIMIT
                    )
                interpreter.process_page(page)
                layout = device.get_result()
                texts: list[str] = []
                for element in layout:
                    if not isinstance(element, LTTextBox):
                        continue
                    text = element.get_text()
                    if not text.strip():
                        continue
                    text_bytes += len(text.encode("utf-8"))
                    if block_count >= max_blocks or text_bytes > max_text_bytes:
                        raise DocumentExtractionError(
                            DocumentExtractionFailure.RESOURCE_LIMIT
                        )
                    texts.append(text)
                    block_count += 1
                # Geometry stays private: only routing booleans leave the child.
                images = []
                pending = list(layout)
                while pending:
                    element = pending.pop()
                    if isinstance(element, LTImage):
                        images.append(element)
                    elif isinstance(element, LTContainer) and not isinstance(
                        element, LTTextBox
                    ):
                        pending.extend(element)
                area = max(0, layout.width) * max(0, layout.height)
                raster_area = sum(
                    max(0, min(image.x1, layout.x1) - max(image.x0, layout.x0))
                    * max(0, min(image.y1, layout.y1) - max(image.y0, layout.y0))
                    for image in images
                )
                pages.append(
                    PdfPageInspection(
                        page_number,
                        tuple(texts),
                        bool(images),
                        area > 0 and raster_area >= area * 0.5,
                        any("\ufffd" in text or "(cid:" in text for text in texts),
                    )
                )
        finally:
            device.close()
        return pages
    except PDFEncryptionError as exc:
        raise DocumentExtractionError(DocumentExtractionFailure.ENCRYPTED) from exc
    except (PDFSyntaxError, PSEOF) as exc:
        raise DocumentExtractionError(DocumentExtractionFailure.MALFORMED) from exc


def _child_main() -> int:
    try:
        import resource

        input_path, output_path = map(Path, sys.argv[1:3])
        max_pages, max_blocks, max_text_bytes, memory_bytes = map(int, sys.argv[3:7])
        # Fail closed if this platform cannot enforce the parser's memory policy.
        if sys.platform != "linux":
            raise RuntimeError("PDF resource enforcement requires Linux")
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        try:
            with input_path.open("rb") as source:
                if sys.argv[7] == "inspect":
                    pages = _inspect_pdf(source, max_pages, max_blocks, max_text_bytes)
                    result: dict[str, object] = {
                        "pages": [
                            [
                                page.page_number,
                                page.texts,
                                page.has_raster,
                                page.substantial_raster,
                                page.unusable_text,
                            ]
                            for page in pages
                        ]
                    }
                else:
                    result = {
                        "blocks": _parse_pdf(
                            source, max_pages, max_blocks, max_text_bytes
                        )
                    }
        except DocumentExtractionError as exc:
            result = {"failure": exc.reason.value}
        with output_path.open("w", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, separators=(",", ":"))
        return 0
    except MemoryError:
        return _MEMORY_LIMIT_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(_child_main())
