import hashlib
import json
from dataclasses import replace
from itertools import pairwise

import pytest
from structlog.testing import capture_logs
from tests.integration.document_processing.conftest import (
    MARKDOWN,
    NOW,
    PDFS,
    TXT,
    admit,
    chunks,
    dispatch,
    document,
    handler,
    pipeline,
)

from nexus.documents.application.extract_document import ExtractDocument
from nexus.documents.application.normalize_document import NormalizeDocument
from nexus.documents.application.open_source import OpenDocumentSource
from nexus.documents.application.segment_document import SegmentDocument
from nexus.documents.application.write_normalized_artifact import (
    WriteNormalizedArtifact,
    canonical_artifact_chunks,
)
from nexus.documents.domain import ExtractedBlockKind
from nexus.infrastructure.extraction.pdf import PdfDocumentExtractor
from nexus.infrastructure.extraction.text import (
    MarkdownDocumentExtractor,
    TxtDocumentExtractor,
)
from nexus.infrastructure.persistence.document import SqlAlchemyDocumentPersistence
from nexus.infrastructure.persistence.document_dispatch import (
    SqlAlchemyDocumentDispatchPersistence,
)
from nexus.infrastructure.persistence.document_reprocessing import (
    SqlAlchemyDocumentReprocessing,
)
from nexus.infrastructure.persistence.file import SqlAlchemyFilePersistence


@pytest.mark.parametrize(
    "data,name,mime",
    [
        (TXT, "quality.txt", "text/plain"),
        (MARKDOWN, "quality.md", "text/markdown"),
        ((PDFS / "quality.pdf").read_bytes(), "quality.pdf", "application/pdf"),
    ],
    ids=["txt", "markdown", "native-pdf"],
)
def test_provenance_survives_all_transforms_and_persistence(run_case, data, name, mime):
    async def run(engine, sessions, storage, client):
        _, message = await admit(engine, sessions, storage, data, name, mime)
        queued = await document(sessions, message)
        started = queued.start_processing(at=NOW, processing_version="dp12-v1")
        await SqlAlchemyDocumentPersistence(sessions).update_document(
            expected=queued, document=started
        )
        extracted = await ExtractDocument(
            source=OpenDocumentSource(
                requests=SqlAlchemyDocumentDispatchPersistence(sessions),
                files=SqlAlchemyFilePersistence(sessions),
                storage=storage,
                max_size_bytes=1024 * 1024,
            ),
            txt=TxtDocumentExtractor(),
            markdown=MarkdownDocumentExtractor(),
            pdf=PdfDocumentExtractor(),
        ).execute(document=started, request=message)
        if name.endswith(".pdf"):
            assert extracted.page_count == 3
            assert [b.page_number for b in extracted.blocks] == [1] * 8 + [3] * 8
            assert all(
                b.kind is ExtractedBlockKind.PARAGRAPH and b.heading_level is None
                for b in extracted.blocks
            )
            assert (
                sum("Nexus synthetic report" in b.text for b in extracted.blocks) == 2
            )
            assert sum("Repeated footer" in b.text for b in extracted.blocks) == 2
            assert (
                sum(
                    "Column A" in b.text and "Column B" in b.text
                    for b in extracted.blocks
                )
                == 2
            )
        elif name.endswith(".md"):
            assert {ExtractedBlockKind.CODE, ExtractedBlockKind.RAW} <= {
                b.kind for b in extracted.blocks
            }
        normalized = NormalizeDocument().execute(extracted)
        expected = SegmentDocument(
            preferred_chunk_bytes=64, max_chunk_bytes=64
        ).execute(normalized)
        await handler(sessions, pipeline(sessions, storage)).execute(message)
        persisted = await chunks(sessions, message)
        assert persisted == expected
        assert [c.index for c in persisted.chunks] == list(range(len(persisted.chunks)))
        originals = {b.index: b for b in extracted.blocks}
        normalized_blocks = {b.source_block_index: b for b in normalized.blocks}
        for chunk in persisted.chunks:
            for contribution in chunk.contributions:
                original = originals[contribution.source_block_index]
                assert (
                    contribution.kind,
                    contribution.start_line,
                    contribution.end_line,
                    contribution.page_number,
                    contribution.list_item,
                    contribution.quote_depth,
                ) == (
                    original.kind,
                    original.start_line,
                    original.end_line,
                    original.page_number,
                    original.list_item,
                    original.quote_depth,
                )
                if (
                    contribution.text_start is not None
                    and len(chunk.contributions) == 1
                ):
                    block = normalized_blocks[contribution.source_block_index]
                    assert (
                        chunk.text
                        == block.text[contribution.text_start : contribution.text_end]
                    )
                if name.endswith(".pdf"):
                    assert contribution.page_number in (1, 3)
                    assert (
                        contribution.start_line is None
                        and contribution.end_line is None
                    )
                else:
                    assert 1 <= contribution.start_line < contribution.end_line
            assert (
                chunk.section_path
                == normalized_blocks[
                    chunk.contributions[0].source_block_index
                ].section_path
            )
        if name.endswith(".md"):
            headings = {
                b.index for b in extracted.blocks if b.heading_level is not None
            }
            assert headings == {0, 2}
            assert any(c.section_path == (0, 2) for c in persisted.chunks)
            assert any(
                p.list_item is not None
                for c in persisted.chunks
                for p in c.contributions
            )
            assert any(
                p.quote_depth == 1 for c in persisted.chunks for p in c.contributions
            )
        for block in normalized.blocks:
            slices = [
                p
                for c in persisted.chunks
                for p in c.contributions
                if p.source_block_index == block.source_block_index
                and p.text_start is not None
            ]
            if slices:
                assert slices[0].text_start == 0 and slices[-1].text_end == len(
                    block.text
                )
                assert all(a.text_end == b.text_start for a, b in pairwise(slices))
                assert (
                    "".join(block.text[p.text_start : p.text_end] for p in slices)
                    == block.text
                )
        if not name.endswith(".pdf"):
            assert any(
                p.text_start is not None
                for c in persisted.chunks
                for p in c.contributions
            )
        artifact = await WriteNormalizedArtifact(storage).execute(
            normalized,
            organization_public_id=started.organization_public_id,
        )
        payload = json.loads(
            b"".join(
                [
                    part
                    async for part in storage.stream_object(
                        storage_key=artifact.storage_key
                    )
                ]
            )
        )
        assert [b["source_block_index"] for b in payload["blocks"]] == [
            b.source_block_index for b in normalized.blocks
        ]
        assert payload == json.loads(b"".join(canonical_artifact_chunks(normalized)))
        assert payload["source_entity_tag"] == extracted.source_entity_tag
        assert payload["extractor_version"] == persisted.extractor_version

    run_case(run)


@pytest.mark.parametrize("changed", [False, True])
def test_explicit_generations_retain_history_and_semantic_output(run_case, changed):
    async def run(engine, sessions, storage, client):
        file, first = await admit(
            engine, sessions, storage, MARKDOWN, "quality.md", "text/markdown"
        )
        await handler(sessions, pipeline(sessions, storage)).execute(first)
        old_document, old_chunks = (
            await document(sessions, first),
            await chunks(sessions, first),
        )
        artifact_bytes = {
            b.name: await (await client.download_blob(b.name)).readall()
            async for b in client.list_blobs(name_starts_with="documents/")
        }
        assert len(artifact_bytes) == 1
        for name, data in artifact_bytes.items():
            assert name.endswith(hashlib.sha256(data).hexdigest() + ".json")
        artifacts_before = [
            (b.name, b.size)
            async for b in client.list_blobs(name_starts_with="documents/")
        ]
        with capture_logs() as generation_logs:
            generation = await SqlAlchemyDocumentReprocessing(
                sessions
            ).create_generation(
                organization_public_id=file.organization_public_id,
                source_file_public_id=file.public_id,
                expected_document_public_id=old_document.public_id,
                at=old_document.processing_completed_at,
            )
        assert [e["event"] for e in generation_logs] == [
            "document_reprocessing_created"
        ]
        assert len(generation_logs[0]["document_correlation"]) == 16
        assert len(generation_logs[0]["file_correlation"]) == 16
        for identity in (
            generation.public_id,
            file.public_id,
            file.organization_public_id,
        ):
            assert str(identity) not in str(generation_logs)
        (second,) = await dispatch(sessions)
        assert generation.public_id != first.document_public_id
        assert second.request_public_id != first.request_public_id
        requests = SqlAlchemyDocumentDispatchPersistence(sessions)
        assert await requests.get_source_facts(
            first
        ) == await requests.get_source_facts(second)
        recipe = "dp12-v2" if changed else "dp12-v1"
        await handler(
            sessions,
            pipeline(
                sessions, storage, recipe=recipe, chunk_bytes=32 if changed else 64
            ),
            recipe=recipe,
        ).execute(second)
        assert await document(sessions, first) == old_document
        assert await chunks(sessions, first) == old_chunks
        assert (await document(sessions, second)).processing_version == recipe
        fresh = await chunks(sessions, second)
        assert fresh.source_entity_tag == old_chunks.source_entity_tag
        if not changed:
            assert fresh == old_chunks
            assert {
                b.name: await (await client.download_blob(b.name)).readall()
                async for b in client.list_blobs(name_starts_with="documents/")
            } == artifact_bytes
            assert [
                (b.name, b.size)
                async for b in client.list_blobs(name_starts_with="documents/")
            ] == artifacts_before
        else:
            assert fresh.max_chunk_bytes == 32 and old_chunks.max_chunk_bytes == 64
            assert (
                replace(
                    fresh,
                    chunks=old_chunks.chunks,
                    preferred_chunk_bytes=64,
                    max_chunk_bytes=64,
                )
                == old_chunks
            )

    run_case(run)
