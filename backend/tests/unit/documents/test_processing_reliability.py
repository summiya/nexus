import asyncio
import hashlib
import threading
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from nexus.documents.application.document_processing_handler import (
    DocumentProcessingHandler,
)
from nexus.documents.application.document_processing_pipeline import (
    DocumentProcessingPipeline,
    _transform,
)
from nexus.documents.application.normalize_document import (
    DocumentNormalizationError,
    DocumentNormalizationFailure,
)
from nexus.documents.application.processing_failures import (
    ProcessingVersionConflict,
    classify_processing_failure,
)
from nexus.documents.domain import Document
from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
)
from nexus.documents.ports.chunk_persistence import (
    ChunkConflictError,
    ChunkPersistenceError,
    StoredChunkCorruptionError,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
)
from nexus.documents.ports.persistence import (
    DocumentConflictError,
    DocumentPersistenceError,
)
from nexus.documents.ports.processing import (
    DocumentProcessingRequested,
    ProcessingOutcome,
    ProcessingRequestRejected,
    ProcessingResult,
)
from nexus.documents.ports.segmentation import (
    DocumentSegmentationError,
    DocumentSegmentationFailure,
)
from nexus.documents.ports.source import DocumentSourceError, DocumentSourceFailure
from nexus.files.ports import FilePersistenceError, ObjectStorageError


def context(*, version="v1"):
    at = datetime.now(UTC)
    doc = Document(uuid4(), uuid4(), uuid4(), created_at=at).start_processing(
        at=at, processing_version=version
    )
    message = DocumentProcessingRequested(
        uuid4(), doc.organization_public_id, doc.public_id
    )
    requests, documents, processor, chunks, finalizer = (AsyncMock() for _ in range(5))
    requests.matches.return_value = True
    documents.get_document.return_value = doc
    chunks.get_chunk_set.return_value = None
    finalizer.finalize.return_value = ProcessingResult(ProcessingOutcome.SUCCESS)
    handler = DocumentProcessingHandler(
        requests=requests,
        documents=documents,
        processor=processor,
        finalizer=finalizer,
        processing_version="v1",
    )
    return doc, message, handler, documents, processor, chunks, finalizer


@pytest.mark.parametrize(
    "error,retryable",
    [
        *(
            (
                DocumentSourceError(f),
                f
                not in (
                    DocumentSourceFailure.INVALID_REQUEST,
                    DocumentSourceFailure.UNAVAILABLE,
                    DocumentSourceFailure.CHANGED,
                    DocumentSourceFailure.TOO_LARGE,
                ),
            )
            for f in DocumentSourceFailure
        ),
        *(
            (
                DocumentExtractionError(f),
                f
                not in (
                    DocumentExtractionFailure.UNSUPPORTED,
                    DocumentExtractionFailure.EMPTY,
                    DocumentExtractionFailure.MALFORMED,
                    DocumentExtractionFailure.RESOURCE_LIMIT,
                    DocumentExtractionFailure.ENCRYPTED,
                ),
            )
            for f in DocumentExtractionFailure
        ),
        *((DocumentNormalizationError(f), False) for f in DocumentNormalizationFailure),
        *((DocumentSegmentationError(f), False) for f in DocumentSegmentationFailure),
        (ProcessingVersionConflict(), False),
        (ChunkConflictError(), False),
        (ChunkPersistenceError(), True),
        (DocumentPersistenceError(), True),
        (FilePersistenceError(), True),
        (ObjectStorageError(), True),
        (DocumentConflictError(), True),
        (RuntimeError("secret"), True),
        (TimeoutError(), True),
    ],
)
def test_failure_policy_is_fixed_and_safe(error, retryable):
    result = classify_processing_failure(error)
    assert result.retryable is retryable
    assert "secret" not in result.failure.safe_message
    assert len(result.failure.code) <= 64
    assert len(result.failure.safe_message) <= 512


def test_transient_then_redelivery_actually_resumes():
    async def run():
        doc, message, handler, documents, processor, _, finalizer = context()
        processor.process.side_effect = [
            DocumentExtractionError(DocumentExtractionFailure.PARSER_FAILURE),
            None,
        ]
        assert (await handler.execute(message)).outcome is ProcessingOutcome.RETRYABLE
        assert (await handler.execute(message)).outcome is ProcessingOutcome.SUCCESS
        assert processor.process.await_count == 2
        assert all(
            c.kwargs["document"] == doc for c in processor.process.await_args_list
        )
        documents.update_document.assert_not_awaited()
        finalizer.finalize.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "error,final_attempt,code",
    [
        (
            DocumentExtractionError(DocumentExtractionFailure.MALFORMED),
            False,
            "MALFORMED_DOCUMENT",
        ),
        (
            DocumentExtractionError(DocumentExtractionFailure.ENCRYPTED),
            False,
            "ENCRYPTED_DOCUMENT",
        ),
        (
            DocumentExtractionError(DocumentExtractionFailure.PARSER_FAILURE),
            True,
            "RETRY_EXHAUSTED",
        ),
        (RuntimeError("private"), True, "RETRY_EXHAUSTED"),
    ],
)
def test_terminal_failure_only_after_durable_finalization(error, final_attempt, code):
    async def run():
        _, message, handler, _, processor, _, finalizer = context()
        processor.process.side_effect = error
        finalizer.finalize.side_effect = [
            DocumentPersistenceError(),
            ProcessingResult(
                ProcessingOutcome.TERMINAL_FINALIZED,
                classify_processing_failure(error).failure,
            ),
        ]
        assert (
            await handler.execute(message, final_attempt=final_attempt)
        ).outcome is ProcessingOutcome.RETRYABLE
        assert (
            await handler.execute(message, final_attempt=final_attempt)
        ).outcome is ProcessingOutcome.TERMINAL_FINALIZED
        assert finalizer.finalize.await_args.kwargs["failure"].code == code

    asyncio.run(run())


@pytest.mark.parametrize("committed", [False, True])
def test_changed_recipe_only_completes_committed_output(committed):
    async def run():
        _, message, handler, documents, _, chunks, finalizer = context(version="old")
        chunks.get_chunk_set.return_value = object() if committed else None
        processor, extraction, *_ = pipeline(documents, chunks, finalizer)
        handler._processor = processor
        await handler.execute(message)
        extraction.execute.assert_not_awaited()
        kwargs = finalizer.finalize.await_args.kwargs
        assert (
            ("failure" not in kwargs)
            if committed
            else kwargs["failure"].code == "PROCESSING_VERSION_CONFLICT"
        )

    asyncio.run(run())


def test_dlq_never_runs_pipeline_and_rejects_foreign_context():
    async def run():
        _, message, handler, _, processor, _, finalizer = context()
        await handler.settle_exhausted(message)
        assert finalizer.finalize.await_args.kwargs["failure"].code == "RETRY_EXHAUSTED"
        processor.process.assert_not_awaited()
        handler._requests.matches.return_value = False
        with pytest.raises(ProcessingRequestRejected):
            await handler.settle_exhausted(message)
        assert finalizer.finalize.await_count == 1

    asyncio.run(run())


def pipeline(documents, chunks, finalizer, *, version="v1"):
    extraction, artifacts = AsyncMock(), AsyncMock()
    from nexus.documents.application.normalize_document import NormalizeDocument
    from nexus.documents.application.segment_document import SegmentDocument

    normalization = Mock(execute=Mock(side_effect=NormalizeDocument().execute))
    segmentation = Mock(execute=Mock(side_effect=SegmentDocument().execute))
    value = DocumentProcessingPipeline(
        documents=documents,
        chunks=chunks,
        finalizer=finalizer,
        extraction=extraction,
        normalization=normalization,
        artifacts=artifacts,
        segmentation=segmentation,
        processing_version=version,
    )
    return value, extraction, normalization, artifacts, segmentation


def test_pipeline_committed_chunks_skip_all_expensive_work_even_old_recipe():
    async def run():
        doc, message, _, documents, _, chunks, finalizer = context(version="old")
        chunks.get_chunk_set.return_value = object()
        value, extraction, normalization, artifacts, segmentation = pipeline(
            documents, chunks, finalizer
        )
        await value.process(document=doc, request=message)
        extraction.execute.assert_not_awaited()
        normalization.execute.assert_not_called()
        artifacts.execute.assert_not_awaited()
        segmentation.execute.assert_not_called()
        finalizer.finalize.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "race", ["none", "same", "different", "terminal", "missing", "unresolved", "recipe"]
)
def test_pipeline_extractor_cas_reconciliation(race):
    async def run():
        doc, message, _, documents, _, chunks, finalizer = context()
        value, extraction, _normalization, artifacts, _segmentation = pipeline(
            documents, chunks, finalizer
        )
        extraction.execute.return_value = ExtractedDocument(
            doc.source_file_public_id,
            "etag",
            "nexus.test",
            "1",
            (ExtractedBlock(0, ExtractedBlockKind.TEXT, "hello", 1, 2),),
        )
        if race != "none":
            documents.update_document.side_effect = DocumentConflictError()
            current = doc
            if race == "same":
                current = doc.record_extractor_version("1")
            if race == "different":
                current = doc.record_extractor_version("2")
            if race == "terminal":
                current = doc.fail(
                    at=datetime.now(UTC), code="TEST", safe_message="safe"
                )
            if race == "missing":
                current = None
            if race == "recipe":
                from dataclasses import replace

                current = replace(doc, processing_version="old")
            documents.get_document.return_value = current
        if race in ("different", "recipe"):
            with pytest.raises(ProcessingVersionConflict):
                await value.process(document=doc, request=message)
        elif race in ("missing", "unresolved"):
            with pytest.raises(DocumentConflictError):
                await value.process(document=doc, request=message)
        else:
            await value.process(document=doc, request=message)
            if race == "terminal":
                chunks.persist_chunk_set.assert_not_awaited()
            else:
                chunks.persist_chunk_set.assert_awaited_once()
                assert (
                    chunks.persist_chunk_set.await_args.kwargs[
                        "expected"
                    ].extractor_version
                    == "1"
                )
                artifacts.execute.assert_awaited_once()
                finalizer.finalize.assert_awaited_once()

    asyncio.run(run())


def test_cancellation_settles_bounded_thread_and_never_fails_document():
    async def run():
        entered, release, settled = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def operation():
            entered.set()
            release.wait(2)
            settled.set()

        task = asyncio.create_task(_transform(operation))
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert settled.is_set()
        _, message, handler, _, processor, _, finalizer = context()
        processor.process.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await handler.execute(message, final_attempt=True)
        finalizer.finalize.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_failed_attempt_reconciles_concurrent_terminal_state(status):
    async def run():
        doc, message, handler, documents, processor, _, finalizer = context()
        terminal = (
            doc.record_extractor_version("1").complete(at=datetime.now(UTC))
            if status == "completed"
            else doc.fail(at=datetime.now(UTC), code="TEST", safe_message="safe")
        )
        documents.get_document.side_effect = [doc, terminal]
        processor.process.side_effect = ChunkConflictError()
        assert (
            await handler.execute(message, final_attempt=True)
        ).outcome is ProcessingOutcome.SUCCESS
        finalizer.finalize.assert_not_awaited()

    asyncio.run(run())


def test_attempt_deadline_retries_then_exhausts_without_detached_processor():
    async def run():
        _, message, handler, _, processor, _, finalizer = context()
        handler._timeout = 0.01
        settled = asyncio.Event()

        async def process(**kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                settled.set()

        processor.process.side_effect = process
        assert (await handler.execute(message)).outcome is ProcessingOutcome.RETRYABLE
        assert settled.is_set()
        finalizer.finalize.assert_not_awaited()
        await handler.execute(message, final_attempt=True)
        assert finalizer.finalize.await_args.kwargs["failure"].code == "RETRY_EXHAUSTED"

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome,failure",
    [
        ("success", None),
        (ProcessingOutcome.SUCCESS, object()),
        (
            ProcessingOutcome.SUCCESS,
            classify_processing_failure(RuntimeError()).failure,
        ),
        (ProcessingOutcome.TERMINAL_FINALIZED, None),
    ],
)
def test_outcome_validation(outcome, failure):
    with pytest.raises((TypeError, ValueError)):
        ProcessingResult(outcome, failure)


def test_corrupt_output_is_a_fixed_non_retryable_failure():
    result = classify_processing_failure(StoredChunkCorruptionError())
    assert not result.retryable
    assert result.failure.code == "PROCESSING_OUTPUT_CORRUPT"
    assert result.failure.safe_message == "The persisted processing output is invalid."


@pytest.mark.parametrize(
    "error,level",
    [
        (RuntimeError("private"), "error"),
        (ChunkPersistenceError(), "warning"),
        (TimeoutError(), "warning"),
    ],
)
def test_unexpected_errors_are_observable_without_sensitive_details(
    error, level, monkeypatch
):
    from nexus.documents.application import document_processing_handler

    logger = Mock()
    monkeypatch.setattr(document_processing_handler, "logger", logger)

    async def run():
        _, message, handler, _, processor, _, _ = context()
        processor.process.side_effect = error
        assert (await handler.execute(message)).outcome is ProcessingOutcome.RETRYABLE
        logged = getattr(logger, level)
        logged.assert_called_once()
        assert set(logged.call_args.kwargs) == {
            "error_type",
            "failure_code",
            "request_correlation",
        }
        assert (
            logged.call_args.kwargs["request_correlation"]
            == hashlib.sha256(str(message.request_public_id).encode()).hexdigest()[:16]
        )
        assert "private" not in str(logged.call_args)
        getattr(logger, "warning" if level == "error" else "error").assert_not_called()

    asyncio.run(run())


def test_stage_logs_are_safe_ordered_and_after_success(monkeypatch):
    import structlog
    from structlog.testing import LogCapture, ReturnLogger

    from nexus.documents.application import document_processing_pipeline as module

    capture = LogCapture()
    monkeypatch.setattr(
        module, "logger", structlog.wrap_logger(ReturnLogger(), processors=[capture])
    )

    async def run():
        doc, message, _, documents, _, chunks, finalizer = context()
        value, extraction, _, _, _ = pipeline(documents, chunks, finalizer)
        extraction.execute.return_value = ExtractedDocument(
            doc.source_file_public_id,
            "private-etag",
            "nexus.txt",
            "1",
            (
                ExtractedBlock(
                    0, ExtractedBlockKind.TEXT, "private document text", 1, 2
                ),
            ),
        )
        ticks = iter(range(10))
        monkeypatch.setattr(module, "monotonic", lambda: next(ticks))
        await value.process(document=doc, request=message)
        logs = capture.entries
        events = [
            e for e in logs if e["event"] == "document_processing_stage_completed"
        ]
        assert [e["stage"] for e in events] == [
            "extraction",
            "normalization",
            "artifact",
            "segmentation",
            "chunks",
        ]
        assert all(e["duration_ms"] == 1000 for e in events)
        assert all(len(e["request_correlation"]) == 16 for e in events)
        serialized = str(logs)
        for sensitive in (
            "private",
            str(doc.public_id),
            str(doc.source_file_public_id),
            str(doc.organization_public_id),
            str(message.request_public_id),
        ):
            assert sensitive not in serialized
        chunks.persist_chunk_set.side_effect = ChunkPersistenceError()
        monkeypatch.setattr(module, "monotonic", lambda: 1)
        capture.entries.clear()
        with pytest.raises(ChunkPersistenceError):
            await value.process(
                document=doc.record_extractor_version("1"), request=message
            )
        assert not any(e.get("stage") == "chunks" for e in capture.entries)

    asyncio.run(run())
