import pytest
from structlog.testing import capture_logs
from tests.integration.document_processing.conftest import (
    MARKDOWN,
    PDFS,
    TXT,
    DeterministicOcr,
    admit,
    chunks,
    document,
    handler,
    pipeline,
)

from nexus.documents.domain import DocumentStatus
from nexus.documents.ports.processing import ProcessingOutcome


@pytest.mark.parametrize(
    "data,name,mime,ocr_pages",
    [
        (TXT, "quality.txt", "text/plain", []),
        (MARKDOWN, "quality.md", "text/markdown", []),
        ((PDFS / "quality.pdf").read_bytes(), "quality.pdf", "application/pdf", []),
        ((PDFS / "mixed.pdf").read_bytes(), "quality.pdf", "application/pdf", [(2,)]),
    ],
    ids=["txt", "markdown", "native-pdf", "pdf-ocr"],
)
def test_supported_formats_complete_real_pipeline(
    run_case, data, name, mime, ocr_pages
):
    async def run(engine, sessions, storage, client):
        ocr = DeterministicOcr()
        with capture_logs() as logs:
            file, message = await admit(engine, sessions, storage, data, name, mime)
            result = await handler(
                sessions, pipeline(sessions, storage, ocr=ocr)
            ).execute(message)
        assert {"document_dispatch_acknowledged", "document_processing_admitted"} <= {
            e["event"] for e in logs
        }
        assert [
            e["stage"]
            for e in logs
            if e["event"] == "document_processing_stage_completed"
        ] == ["extraction", "normalization", "artifact", "segmentation", "chunks"]
        for sensitive in (
            name,
            file.storage_key,
            str(file.public_id),
            str(file.organization_public_id),
            str(message.document_public_id),
            str(message.request_public_id),
            "First paragraph",
            "OCR page",
        ):
            assert sensitive not in str(logs)
        assert result.outcome is ProcessingOutcome.SUCCESS
        assert (await document(sessions, message)).status is DocumentStatus.COMPLETED
        output = await chunks(sessions, message)
        assert output.source_file_public_id == file.public_id
        assert (
            output.source_entity_tag
            == (
                await storage.get_object_properties(storage_key=file.storage_key)
            ).entity_tag
        )
        assert all(chunk.text.strip() for chunk in output.chunks)
        assert all(len(chunk.text.encode()) <= 64 for chunk in output.chunks)
        assert ocr.calls == ocr_pages
        artifacts = [
            blob async for blob in client.list_blobs(name_starts_with="documents/")
        ]
        assert len(artifacts) == 1
        if name.endswith(".pdf"):
            pages = {p for chunk in output.chunks for p in chunk.page_numbers}
            assert pages == ({1, 2, 4} if ocr_pages else {1, 3})

    run_case(run)


@pytest.mark.parametrize(
    "data,name,mime,code",
    [
        (b" \n\t", "empty.txt", "text/plain", "EMPTY_DOCUMENT"),
        (b" \n", "empty.md", "text/markdown", "EMPTY_DOCUMENT"),
        (b"\xff", "invalid.txt", "text/plain", "MALFORMED_DOCUMENT"),
        (b"not a PDF", "broken.pdf", "application/pdf", "MALFORMED_DOCUMENT"),
        (
            (PDFS / "encrypted.pdf").read_bytes(),
            "encrypted.pdf",
            "application/pdf",
            "ENCRYPTED_DOCUMENT",
        ),
    ],
)
def test_invalid_content_fails_without_partial_chunks(run_case, data, name, mime, code):
    async def run(engine, sessions, storage, client):
        _, message = await admit(engine, sessions, storage, data, name, mime)
        result = await handler(sessions, pipeline(sessions, storage)).execute(message)
        assert result.outcome is ProcessingOutcome.TERMINAL_FINALIZED
        assert (await document(sessions, message)).status is DocumentStatus.FAILED
        assert (await document(sessions, message)).failure.code == code
        assert await chunks(sessions, message) is None
        assert not [
            blob async for blob in client.list_blobs(name_starts_with="documents/")
        ]

    run_case(run)


def test_unsupported_file_does_not_initiate_document(run_case):
    async def run(engine, sessions, storage, client):
        _, message = await admit(
            engine, sessions, storage, b"unsupported", "image.png", "image/png"
        )
        assert message is None

    run_case(run)


@pytest.mark.parametrize("change", ["missing", "changed", "limit"])
def test_exact_source_and_resource_admission(run_case, change):
    async def run(engine, sessions, storage, client):
        file, message = await admit(engine, sessions, storage, TXT)
        if change == "missing":
            await client.delete_blob(file.storage_key)
        elif change == "changed":
            await client.upload_blob(file.storage_key, b"changed", overwrite=True)
        result = await handler(
            sessions,
            pipeline(
                sessions,
                storage,
                max_bytes=1 if change == "limit" else 1024 * 1024,
            ),
        ).execute(message)
        assert result.outcome is ProcessingOutcome.TERMINAL_FINALIZED
        assert (await document(sessions, message)).status is DocumentStatus.FAILED
        assert (await document(sessions, message)).failure.code == {
            "missing": "SOURCE_UNAVAILABLE",
            "changed": "SOURCE_CHANGED",
            "limit": "DOCUMENT_RESOURCE_LIMIT",
        }[change]
        assert await chunks(sessions, message) is None

    run_case(run)
