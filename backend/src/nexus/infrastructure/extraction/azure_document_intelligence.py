"""Azure Read OCR: one borrowed async client, bounded page-selective operations."""

import asyncio
import math
from collections.abc import Mapping
from io import BytesIO

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeResult,
    DocumentLine,
    DocumentParagraph,
    DocumentSpan,
)
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)

from nexus.documents.domain.extracted_document import ExtractedBlockKind
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    OcrBlock,
    OcrPage,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionFailure as Failure,
)
from nexus.infrastructure.extraction.pdf import DEFAULT_MAX_PDF_PAGES
from nexus.infrastructure.extraction.text import (
    DEFAULT_MAX_EXTRACTION_BLOCKS,
    DEFAULT_MAX_EXTRACTION_BYTES,
)

AZURE_READ_MODEL = "prebuilt-read"
AZURE_READ_API_VERSION = "2024-11-30"
DEFAULT_OCR_DEADLINE_SECONDS = 120.0


class AzureDocumentIntelligenceOcr:
    """The caller owns client/credential lifecycle. No retries or background tasks."""

    def __init__(
        self,
        client: DocumentIntelligenceClient,
        *,
        concurrency: int = 2,
        timeout_seconds: float = DEFAULT_OCR_DEADLINE_SECONDS,
        max_bytes: int = DEFAULT_MAX_EXTRACTION_BYTES,
        max_pages: int = DEFAULT_MAX_PDF_PAGES,
        max_blocks: int = DEFAULT_MAX_EXTRACTION_BLOCKS,
        max_text_bytes: int = DEFAULT_MAX_EXTRACTION_BYTES,
    ) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (
                concurrency,
                max_bytes,
                max_pages,
                max_blocks,
                max_text_bytes,
            )
        ):
            raise ValueError("Invalid OCR limits")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Invalid OCR deadline")
        self._client = client
        self._slots = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._max_blocks = max_blocks
        self._max_text_bytes = max_text_bytes

    async def extract_pages(
        self, pdf_bytes: bytes, *, page_numbers: tuple[int, ...]
    ) -> tuple[OcrPage, ...]:
        if (
            type(pdf_bytes) is not bytes
            or not pdf_bytes
            or type(page_numbers) is not tuple
            or not page_numbers
            or any(type(page) is not int or page < 1 for page in page_numbers)
            or page_numbers != tuple(sorted(set(page_numbers)))
        ):
            raise DocumentExtractionError(Failure.MALFORMED)
        if len(pdf_bytes) > self._max_bytes or page_numbers[-1] > self._max_pages:
            raise DocumentExtractionError(Failure.RESOURCE_LIMIT)
        try:
            # Admission wait is part of the deadline; cancellation is never shielded.
            async with asyncio.timeout(self._timeout), self._slots:
                with BytesIO(pdf_bytes) as body:
                    poller = await self._client.begin_analyze_document(
                        AZURE_READ_MODEL,
                        body=body,
                        pages=",".join(map(str, page_numbers)),
                        content_type="application/pdf",
                        string_index_type="unicodeCodePoint",
                        polling_interval=2,
                        retry_total=0,
                        connection_timeout=20,
                        read_timeout=20,
                    )
                result = await poller.result()
                return self._map_result(result, page_numbers)
        except ClientAuthenticationError as exc:
            raise DocumentExtractionError(Failure.PROVIDER_ACCESS) from exc
        except HttpResponseError as exc:
            reason = Failure.PROVIDER_FAILURE
            if exc.status_code in (401, 403, 404):
                reason = Failure.PROVIDER_ACCESS
            elif exc.status_code in (408, 429) or (
                exc.status_code is not None and exc.status_code >= 500
            ):
                reason = Failure.PROVIDER_TRANSIENT
            elif _is_invalid_content(exc):
                reason = Failure.MALFORMED
            raise DocumentExtractionError(reason) from exc
        except (TimeoutError, ServiceRequestError, ServiceResponseError) as exc:
            raise DocumentExtractionError(Failure.PROVIDER_TRANSIENT) from exc
        except (AzureError, ValueError, TypeError, AttributeError) as exc:
            raise DocumentExtractionError(Failure.PROVIDER_FAILURE) from exc

    def _map_result(
        self, result: AnalyzeResult, selected: tuple[int, ...]
    ) -> tuple[OcrPage, ...]:
        if (
            result.model_id != AZURE_READ_MODEL
            or result.api_version != AZURE_READ_API_VERSION
            or type(result.content) is not str
            or not result.pages
            or tuple(sorted(page.page_number for page in result.pages)) != selected
        ):
            raise DocumentExtractionError(Failure.PROVIDER_FAILURE)
        if len(result.content.encode("utf-8")) > self._max_text_bytes:
            raise DocumentExtractionError(Failure.RESOURCE_LIMIT)
        if any(type(page.page_number) is not int for page in result.pages):
            raise DocumentExtractionError(Failure.PROVIDER_FAILURE)
        paragraphs_by_page: dict[int, list[DocumentParagraph]] = {
            number: [] for number in selected
        }
        fallback_pages: set[int] = set()
        paragraphs = result.paragraphs or []
        if len(paragraphs) > self._max_blocks:
            raise DocumentExtractionError(Failure.RESOURCE_LIMIT)
        for paragraph in paragraphs:
            regions = paragraph.bounding_regions or []
            if not regions:
                # Unattributed paragraphs cannot safely be used. Page lines remain reliable.
                fallback_pages.update(selected)
                continue
            numbers = {region.page_number for region in regions}
            if any(
                type(number) is not int or number not in selected for number in numbers
            ):
                raise DocumentExtractionError(Failure.PROVIDER_FAILURE)
            if len(numbers) != 1:
                fallback_pages.update(numbers)
                continue
            paragraphs_by_page[next(iter(numbers))].append(paragraph)
        output: list[OcrPage] = []
        count = text_bytes = 0
        for page in sorted(result.pages, key=lambda page: page.page_number):
            paragraphs = paragraphs_by_page[page.page_number]
            units: list[DocumentLine | DocumentParagraph]
            # Use one representation for the whole page, never paragraph + line text.
            if page.page_number in fallback_pages or not paragraphs:
                units = list(page.lines or [])
                kind = ExtractedBlockKind.TEXT
            else:
                units = list(paragraphs)
                kind = ExtractedBlockKind.PARAGRAPH
            if len(units) + count > self._max_blocks:
                raise DocumentExtractionError(Failure.RESOURCE_LIMIT)
            ordered = sorted(
                units, key=lambda unit: self._span_offset(unit.spans, result.content)
            )
            blocks = []
            previous_end = 0
            for unit in ordered:
                offset = self._span_offset(unit.spans, result.content)
                if type(unit.content) is not str or offset < previous_end:
                    raise DocumentExtractionError(Failure.PROVIDER_FAILURE)
                previous_end = max(
                    span.offset + span.length for span in unit.spans or []
                )
                if not unit.content.strip():
                    continue
                count += 1
                text_bytes += len(unit.content.encode("utf-8"))
                if count > self._max_blocks or text_bytes > self._max_text_bytes:
                    raise DocumentExtractionError(Failure.RESOURCE_LIMIT)
                blocks.append(OcrBlock(kind, unit.content))
            output.append(OcrPage(page.page_number, tuple(blocks)))
        return tuple(output)

    @staticmethod
    def _span_offset(spans: list[DocumentSpan] | None, content: str) -> int:
        if not spans or any(
            type(span.offset) is not int
            or type(span.length) is not int
            or span.offset < 0
            or span.length <= 0
            or span.offset + span.length > len(content)
            for span in spans
        ):
            raise DocumentExtractionError(Failure.PROVIDER_FAILURE)
        return min(span.offset for span in spans)


def _is_invalid_content(exc: HttpResponseError) -> bool:
    """Use SDK-parsed document error codes only; never inspect error messages."""
    error = exc.error
    if error is None:
        return False
    codes = ("InvalidContent", "UnsupportedContent")
    inner = error.innererror
    inner_code = inner.get("code") if isinstance(inner, Mapping) else None
    return error.code in codes or inner_code in codes
