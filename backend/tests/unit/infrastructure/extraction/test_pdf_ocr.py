import asyncio
from pathlib import Path
from uuid import UUID

import pytest

from nexus.documents.domain.extracted_document import ExtractedBlockKind as Kind
from nexus.documents.ports.extraction import DocumentExtractionError, OcrBlock, OcrPage
from nexus.documents.ports.extraction import DocumentExtractionFailure as Failure
from nexus.documents.ports.source import (
    DocumentSource,
    DocumentSourceError,
    DocumentSourceFailure,
)
from nexus.infrastructure.extraction.pdf import PdfDocumentExtractor, PdfPageInspection
from nexus.infrastructure.extraction.pdf_ocr import PdfWithOcrDocumentExtractor

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "extraction"


def source(data):
    async def stream():
        for offset in range(0, len(data), 31):
            yield data[offset : offset + 31]

    return DocumentSource(
        UUID(int=1), "source.pdf", "application/pdf", "verified", len(data), stream()
    )


class FakeOcr:
    def __init__(self, pages=None):
        self.calls = []
        self.pages = pages

    async def extract_pages(self, data, *, page_numbers):
        self.calls.append((data, page_numbers))
        return (
            self.pages
            if self.pages is not None
            else tuple(
                OcrPage(page, (OcrBlock(Kind.TEXT, "OCR Ω"),)) for page in page_numbers
            )
        )


@pytest.mark.parametrize("name", ["single.pdf", "multi.pdf", "unicode.pdf"])
def test_native_only_preserves_dp07_output_and_never_calls_ocr(name):
    async def run():
        data = (FIXTURES / name).read_bytes()
        ocr = FakeOcr()
        native = PdfDocumentExtractor()
        result = await PdfWithOcrDocumentExtractor(native, ocr).extract(source(data))
        assert result == await native.extract(source(data))
        assert not ocr.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,expected",
    [
        ("mixed.pdf", [(1, "Native one\n"), (2, "OCR Ω"), (4, "Native four\n")]),
        ("scan-footer.pdf", [(1, "Native one\n"), (2, "OCR Ω"), (3, "Native three\n")]),
        ("image-only.pdf", [(1, "OCR Ω")]),
    ],
)
def test_selected_pages_replace_native_text_preserve_original_pages_and_metadata(
    name, expected
):
    async def run():
        data = (FIXTURES / name).read_bytes()
        ocr = FakeOcr()
        extractor = PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), ocr)
        result = await extractor.extract(source(data))
        assert [(b.page_number, b.text) for b in result.blocks] == expected
        assert [b.index for b in result.blocks] == list(range(len(expected)))
        assert all(b.start_line is None and b.end_line is None for b in result.blocks)
        assert result.source_file_public_id == UUID(int=1)
        assert result.source_entity_tag == "verified"
        assert (result.extractor_id, result.extractor_version) == ("nexus.pdf-ocr", "1")
        assert ocr.calls == [(data, (1,) if name == "image-only.pdf" else (2,))]
        assert result == await extractor.extract(source(data))

    asyncio.run(run())


@pytest.mark.parametrize(
    "page,expected",
    [
        (PdfPageInspection(1, (), False, False, False), False),
        (PdfPageInspection(1, (), True, False, False), True),
        (PdfPageInspection(1, ("A",), False, False, False), False),
        (PdfPageInspection(1, ("A",), True, False, False), False),
        (PdfPageInspection(1, ("Footer",), True, True, False), True),
        (PdfPageInspection(1, ("(cid:10)",), False, False, True), True),
    ],
)
def test_routing_is_explicit_and_short_native_text_is_valid(page, expected):
    assert page.needs_ocr is expected


@pytest.mark.parametrize(
    "name,reason",
    [
        ("empty.pdf", Failure.EMPTY),
        ("encrypted.pdf", Failure.ENCRYPTED),
        ("encrypted-empty-password.pdf", Failure.ENCRYPTED),
    ],
)
def test_blank_and_rejected_native_documents_do_not_trigger_ocr(name, reason):
    ocr = FakeOcr()
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(
            PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), ocr).extract(
                source((FIXTURES / name).read_bytes())
            )
        )
    assert exc.value.reason is reason
    assert not ocr.calls


@pytest.mark.parametrize(
    "pages",
    [
        (),
        (OcrPage(1, (OcrBlock(Kind.TEXT, "wrong page"),)),),
        (
            OcrPage(2, (OcrBlock(Kind.TEXT, "a"),)),
            OcrPage(2, (OcrBlock(Kind.TEXT, "b"),)),
        ),
    ],
)
def test_partial_wrong_or_duplicate_ocr_pages_fail_whole_document(pages):
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(
            PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), FakeOcr(pages)).extract(
                source((FIXTURES / "mixed.pdf").read_bytes())
            )
        )
    assert exc.value.reason is Failure.PROVIDER_FAILURE


def test_empty_ocr_page_does_not_duplicate_native_footer():
    result = asyncio.run(
        PdfWithOcrDocumentExtractor(
            PdfDocumentExtractor(), FakeOcr((OcrPage(2, ()),))
        ).extract(source((FIXTURES / "scan-footer.pdf").read_bytes()))
    )
    assert [block.page_number for block in result.blocks] == [1, 3]


@pytest.mark.parametrize("limits", [{"max_blocks": 2}, {"max_text_bytes": 25}])
def test_combined_native_and_ocr_limits(limits):
    # Native alone fits; adding OCR must fail instead of returning partial output.
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(
            PdfWithOcrDocumentExtractor(
                PdfDocumentExtractor(**limits), FakeOcr()
            ).extract(source((FIXTURES / "mixed.pdf").read_bytes()))
        )
    assert exc.value.reason is Failure.RESOURCE_LIMIT


def test_empty_scanned_document_fails_after_ocr():
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(
            PdfWithOcrDocumentExtractor(
                PdfDocumentExtractor(), FakeOcr((OcrPage(1, ()),))
            ).extract(source((FIXTURES / "image-only.pdf").read_bytes()))
        )
    assert exc.value.reason is Failure.EMPTY


def test_verified_eof_is_required_before_native_or_ocr(monkeypatch):
    from dataclasses import replace

    failure = DocumentSourceError(DocumentSourceFailure.CHANGED)

    async def broken():
        yield (FIXTURES / "image-only.pdf").read_bytes()
        raise failure

    ocr = FakeOcr()
    with pytest.raises(DocumentSourceError) as exc:
        asyncio.run(
            PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), ocr).extract(
                replace(source(b""), content=broken())
            )
        )
    assert exc.value is failure
    assert not ocr.calls


def test_cancellation_during_ocr_propagates_without_tasks():
    async def run():
        started, cleaned = asyncio.Event(), asyncio.Event()

        class WaitingOcr:
            async def extract_pages(self, data, *, page_numbers):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()

        task = asyncio.create_task(
            PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), WaitingOcr()).extract(
                source((FIXTURES / "image-only.pdf").read_bytes())
            )
        )
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(run())


@pytest.mark.parametrize(
    "page,texts",
    [(True, (OcrBlock(Kind.TEXT, "a"),)), (0, ()), (1, ["a"]), (1, (True,))],
)
def test_page_ocr_values_reject_invalid_python_types(page, texts):
    with pytest.raises(ValueError):
        OcrPage(page, texts)


def test_malformed_pdf_does_not_fall_back_to_ocr():
    ocr = FakeOcr()
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(
            PdfWithOcrDocumentExtractor(PdfDocumentExtractor(), ocr).extract(
                source(b"not a PDF")
            )
        )
    assert exc.value.reason is Failure.MALFORMED
    assert not ocr.calls


@pytest.mark.parametrize("kind", [Kind.TEXT, Kind.PARAGRAPH])
def test_composite_preserves_ocr_kind_without_duplicate_native_page_text(kind):
    result = asyncio.run(
        PdfWithOcrDocumentExtractor(
            PdfDocumentExtractor(),
            FakeOcr((OcrPage(2, (OcrBlock(kind, "OCR page two"),)),)),
        ).extract(source((FIXTURES / "scan-footer.pdf").read_bytes()))
    )
    assert [(block.page_number, block.kind, block.text) for block in result.blocks] == [
        (1, Kind.PARAGRAPH, "Native one\n"),
        (2, kind, "OCR page two"),
        (3, Kind.PARAGRAPH, "Native three\n"),
    ]
    assert [block.index for block in result.blocks] == [0, 1, 2]


@pytest.mark.parametrize(
    "kind,text", [("text", "a"), (Kind.HEADING, "a"), (Kind.TEXT, True)]
)
def test_ocr_blocks_reject_invalid_kinds_and_text_types(kind, text):
    with pytest.raises(ValueError):
        OcrBlock(kind, text)


def test_pdf_inspection_and_limits_are_explicit_infrastructure_api():
    data = (FIXTURES / "multi.pdf").read_bytes()
    native = PdfDocumentExtractor(max_blocks=3, max_text_bytes=100)
    inspected_data, pages = asyncio.run(native.inspect_source(source(data)))
    assert inspected_data == data
    assert [(page.page_number, page.texts) for page in pages] == [
        (1, ("Page one\n",)),
        (2, ()),
        (3, ("Page three\n",)),
    ]
    assert native.max_blocks == 3
    assert native.max_text_bytes == 100
    with pytest.raises(AttributeError):
        native.max_blocks = 100
    with pytest.raises(AttributeError):
        native.max_text_bytes = 1000
