import asyncio
import subprocess
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event, get_ident
from uuid import UUID

import pytest

from nexus.documents.domain import ExtractedBlockKind
from nexus.documents.ports.extraction import DocumentExtractionError
from nexus.documents.ports.extraction import DocumentExtractionFailure as Failure
from nexus.documents.ports.source import (
    DocumentSource,
    DocumentSourceError,
    DocumentSourceFailure,
)
from nexus.infrastructure.extraction import pdf as adapter
from nexus.infrastructure.extraction.pdf import PdfDocumentExtractor

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "extraction"


def source(data, *, content=None):
    async def stream():
        for start in range(0, len(data), 1024):
            yield data[start : start + 1024]

    return DocumentSource(
        UUID(int=1),
        "source.pdf",
        "application/pdf",
        "verified-version",
        len(data),
        stream() if content is None else content,
    )


def extract(name="single.pdf", **limits):
    return asyncio.run(
        PdfDocumentExtractor(**limits).extract(source((FIXTURES / name).read_bytes()))
    )


def test_single_page_text_boxes_metadata_and_default_memory_policy():
    result = extract()
    assert [block.text for block in result.blocks] == [
        "First paragraph\n",
        "Second paragraph\n",
    ]
    assert [block.index for block in result.blocks] == [0, 1]
    assert all(
        block.page_number == 1 and block.start_line is None and block.end_line is None
        for block in result.blocks
    )
    assert all(
        block.kind is ExtractedBlockKind.PARAGRAPH and block.heading_level is None
        for block in result.blocks
    )
    assert result.source_file_public_id == UUID(int=1)
    assert result.source_entity_tag == "verified-version"
    assert (result.extractor_id, result.extractor_version) == ("nexus.pdf", "1")
    assert adapter.DEFAULT_PDF_MEMORY_BYTES == 512 * 1024 * 1024


def test_page_order_skips_empty_pages_without_renumbering_and_is_deterministic():
    result = extract("multi.pdf")
    assert [
        (block.index, block.page_number, block.text) for block in result.blocks
    ] == [(0, 1, "Page one\n"), (1, 3, "Page three\n")]
    assert result == extract("multi.pdf")


def test_unicode_text_is_preserved():
    assert extract("unicode.pdf").blocks[0].text == "Café Ω\n"


def test_recoverable_catalog_type_uses_pinned_parser_defaults(monkeypatch):
    from pdfminer import settings
    from pdfminer.high_level import extract_text
    from pdfminer.pdfparser import PDFSyntaxError

    data = (FIXTURES / "single.pdf").read_bytes()
    assert data.count(b"/Type /Catalog") == 1
    # Equal-length replacement preserves every xref offset and the intact page tree.
    data = data.replace(b"/Type /Catalog", b"/Type /Unknown")
    assert settings.STRICT is False
    assert "First paragraph" in extract_text(BytesIO(data))
    with monkeypatch.context() as strict:
        strict.setattr(settings, "STRICT", True)
        with pytest.raises(PDFSyntaxError):
            extract_text(BytesIO(data))

    result = asyncio.run(PdfDocumentExtractor().extract(source(data)))
    assert [block.text for block in result.blocks] == [
        "First paragraph\n",
        "Second paragraph\n",
    ]


@pytest.mark.parametrize(
    "name,reason",
    [
        ("empty.pdf", Failure.EMPTY),
        ("image-only.pdf", Failure.EMPTY),
        ("encrypted.pdf", Failure.ENCRYPTED),
        ("encrypted-empty-password.pdf", Failure.ENCRYPTED),
    ],
)
def test_empty_and_encrypted_files_fail_safely(name, reason):
    with pytest.raises(DocumentExtractionError) as exc:
        extract(name)
    assert exc.value.reason is reason
    assert str(exc.value) == "Document extraction failed"


@pytest.mark.parametrize(
    "data", [b"", b"not a PDF", b"%PDF-1.7\n%%EOF", b"%PDF-1.7\nbroken", None]
)
def test_malformed_and_truncated_pdf(data):
    if data is None:
        data = (FIXTURES / "single.pdf").read_bytes()[:-20]
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(PdfDocumentExtractor().extract(source(data)))
    assert exc.value.reason is Failure.MALFORMED


@pytest.mark.parametrize(
    "limits", [{"max_pages": 2}, {"max_blocks": 1}, {"max_text_bytes": 3}]
)
def test_page_block_and_text_limits_reject_whole_result(limits):
    with pytest.raises(DocumentExtractionError) as exc:
        extract("multi.pdf", **limits)
    assert exc.value.reason is Failure.RESOURCE_LIMIT


def test_real_compressed_pdf_respects_parser_memory_limit():
    with pytest.raises(DocumentExtractionError) as exc:
        extract("compressed-memory.pdf", memory_bytes=96 * 1024 * 1024)
    assert exc.value.reason is Failure.RESOURCE_LIMIT


@pytest.mark.parametrize("overflow", [False, True])
def test_input_limit_prevents_starting_parser(monkeypatch, overflow):
    def unexpected(*args):
        pytest.fail("Parser must not start")

    monkeypatch.setattr(adapter, "_parse_in_process", unexpected)
    value = source(b"four")
    if overflow:
        value = replace(value, expected_size_bytes=1)
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(PdfDocumentExtractor(max_bytes=3).extract(value))
    assert exc.value.reason is Failure.RESOURCE_LIMIT


def test_source_failure_before_verified_eof_never_starts_parser(monkeypatch):
    failure = DocumentSourceError(DocumentSourceFailure.CHANGED)

    async def stream():
        yield (FIXTURES / "single.pdf").read_bytes()
        raise failure

    def unexpected(*args):
        pytest.fail("Parser must not start")

    monkeypatch.setattr(adapter, "_parse_in_process", unexpected)
    with pytest.raises(DocumentSourceError) as exc:
        asyncio.run(PdfDocumentExtractor().extract(source(b"", content=stream())))
    assert exc.value is failure


def test_parser_failure_has_no_private_message(monkeypatch):
    def fail(*args):
        raise RuntimeError("private PDF content")

    monkeypatch.setattr(adapter, "_parse_in_process", fail)
    with pytest.raises(DocumentExtractionError) as exc:
        extract()
    assert exc.value.reason is Failure.PARSER_FAILURE
    assert "private" not in str(exc.value)


def test_parser_launch_and_result_mapping_run_off_event_loop(monkeypatch):
    original = adapter._parse_in_process
    event_loop_thread = get_ident()

    def checked(*args):
        assert get_ident() != event_loop_thread
        return original(*args)

    monkeypatch.setattr(adapter, "_parse_in_process", checked)
    assert extract().blocks


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_repeated_cancellation_kill_reap_and_remove_files(
    monkeypatch, cancel
):
    original = subprocess.Popen
    started = Event()
    processes = []
    directories = []

    def slow_parser(command, **kwargs):
        directories.append(Path(command[3]).parent)
        process = original(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
        )
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(adapter.subprocess, "Popen", slow_parser)

    async def run():
        extractor = PdfDocumentExtractor(timeout_seconds=30 if cancel else 0.05)
        task = asyncio.create_task(
            extractor.extract(source((FIXTURES / "single.pdf").read_bytes()))
        )
        if cancel:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(DocumentExtractionError) as exc:
                await task
            assert exc.value.reason is Failure.RESOURCE_LIMIT
        assert len(processes) == 1
        assert processes[0].returncode is not None
        assert processes[0].wait(timeout=1) == processes[0].returncode
        assert all(not directory.exists() for directory in directories)

    asyncio.run(run())


def test_failed_child_is_reaped_without_exposing_stderr(monkeypatch):
    original = subprocess.Popen
    processes = []
    directories = []

    def failed_parser(command, **kwargs):
        directories.append(Path(command[3]).parent)
        process = original(
            [sys.executable, "-c", "raise RuntimeError('private PDF contents')"],
            **kwargs,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(adapter.subprocess, "Popen", failed_parser)
    with pytest.raises(DocumentExtractionError) as exc:
        extract()
    assert exc.value.reason is Failure.PARSER_FAILURE
    assert "private" not in str(exc.value)
    assert processes[0].returncode == 1
    assert all(not directory.exists() for directory in directories)


def test_cancellation_during_child_startup_still_reaps_child(monkeypatch):
    original = subprocess.Popen
    starting, release = Event(), Event()
    processes = []

    def delayed_start(command, **kwargs):
        starting.set()
        assert release.wait(5)
        process = original(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(adapter.subprocess, "Popen", delayed_start)

    async def run():
        task = asyncio.create_task(
            PdfDocumentExtractor().extract(
                source((FIXTURES / "single.pdf").read_bytes())
            )
        )
        try:
            assert await asyncio.to_thread(starting.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(processes) == 1
        assert processes[0].returncode is not None

    asyncio.run(run())


@pytest.mark.parametrize(
    "limits",
    [
        {"max_bytes": 0},
        {"max_blocks": True},
        {"max_pages": -1},
        {"max_text_bytes": 1.0},
        {"memory_bytes": False},
        {"timeout_seconds": True},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 0},
    ],
)
def test_limits_require_positive_finite_values(limits):
    with pytest.raises(ValueError):
        PdfDocumentExtractor(**limits)
