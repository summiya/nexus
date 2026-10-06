from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nexus.documents.application.normalize_document import (
    DocumentNormalizationError,
    NormalizeDocument,
)
from nexus.documents.application.normalize_document import (
    DocumentNormalizationFailure as Failure,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedDocument,
    ExtractedListItem,
)
from nexus.documents.domain.extracted_document import (
    ExtractedBlockKind as Kind,
)


def extracted(*blocks, page_count=None):
    return ExtractedDocument(
        UUID(int=1), "verified-etag", "nexus.commonmark", "1", tuple(blocks), page_count
    )


def line(index, kind, text, **kwargs):
    return ExtractedBlock(index, kind, text, index + 1, index + 2, **kwargs)


@pytest.mark.parametrize("ending", ["\r\n", "\r", "\n"])
def test_newlines_unicode_and_conservative_prose_whitespace(ending):
    result = NormalizeDocument().execute(
        extracted(
            line(0, Kind.TEXT, f"  Cafe\u0301  Ω\t {ending}aligned   columns \t"),
            line(1, Kind.PARAGRAPH, f"{ending}  internal   spaces\t {ending}"),
        )
    )
    assert [b.text for b in result.blocks] == [
        "  Café  Ω\naligned   columns",
        "  internal   spaces",
    ]
    assert result.source_file_public_id == UUID(int=1)
    assert result.source_entity_tag == "verified-etag"
    assert (result.extractor_id, result.extractor_version) == ("nexus.commonmark", "1")
    assert (result.normalizer_id, result.normalizer_version) == (
        "nexus.normalization",
        "1",
    )
    assert result == NormalizeDocument().execute(
        extracted(
            line(0, Kind.TEXT, f"  Cafe\u0301  Ω\t {ending}aligned   columns \t"),
            line(1, Kind.PARAGRAPH, f"{ending}  internal   spaces\t {ending}"),
        )
    )


@pytest.mark.parametrize("kind", [Kind.CODE, Kind.RAW])
def test_code_raw_only_normalize_newlines(kind):
    text = "  Cafe\u0301\t \r\n  x   y\r\n"
    assert (
        NormalizeDocument().execute(extracted(line(0, kind, text))).blocks[0].text
        == "  Cafe\u0301\t \n  x   y\n"
    )


def test_sections_lists_quotes_blanks_and_breaks_preserve_source_references():
    item = ExtractedListItem(3, 3, 2, True, 0)
    source = extracted(
        line(0, Kind.HEADING, "  Architecture\t  choices  ", heading_level=1),
        line(1, Kind.HEADING, "Storage", heading_level=3),
        line(2, Kind.PARAGRAPH, "item", list_item=item, quote_depth=2),
        line(3, Kind.HEADING, "\t ", heading_level=2),
        line(4, Kind.TEXT, " \t"),
        line(5, Kind.THEMATIC_BREAK, ""),
        line(6, Kind.HEADING, "Next", heading_level=2),
        line(7, Kind.PARAGRAPH, "body"),
        line(8, Kind.HEADING, "Reset", heading_level=1),
    )
    result = NormalizeDocument().execute(source)
    assert [b.section_path for b in result.blocks] == [
        (0,),
        (0, 1),
        (0, 1),
        (0, 1),
        (0, 1),
        (0, 1),
        (0, 6),
        (0, 6),
        (8,),
    ]
    assert result.blocks[0].text == "Architecture choices"
    assert result.blocks[2].list_item == item
    assert result.blocks[2].quote_depth == 2
    assert result.blocks[3].text == result.blocks[4].text == result.blocks[5].text == ""
    for source_block, block in zip(source.blocks, result.blocks, strict=True):
        assert block.source_block_index == source_block.index
        assert (block.start_line, block.end_line, block.kind, block.heading_level) == (
            source_block.start_line,
            source_block.end_line,
            source_block.kind,
            source_block.heading_level,
        )
    assert result.page_count is None
    assert "Architecture" not in repr(result) and "Architecture" not in repr(
        result.blocks[0]
    )
    with pytest.raises(FrozenInstanceError):
        result.normalizer_version = "2"
    with pytest.raises(FrozenInstanceError):
        result.blocks[0].text = "changed"


@pytest.mark.parametrize("pages", [2, 5])
def test_repeated_page_edges_and_body_are_never_removed(pages):
    blocks = tuple(
        ExtractedBlock(index, Kind.PARAGRAPH, text, page_number=page)
        for index, (page, text) in enumerate(
            (page, text)
            for page in range(1, pages + 1)
            for text in ("Header", "Repeated body", "Footer")
        )
    )
    result = NormalizeDocument().execute(extracted(*blocks, page_count=pages))
    assert [(b.text, b.page_number, b.source_block_index) for b in result.blocks] == [
        (b.text, b.page_number, b.index) for b in blocks
    ]


def test_page_gaps_and_trailing_empty_pages_survive_without_synthetic_blocks():
    result = NormalizeDocument().execute(
        extracted(
            ExtractedBlock(0, Kind.PARAGRAPH, "one", page_number=1),
            ExtractedBlock(1, Kind.TEXT, "OCR three", page_number=3),
            page_count=5,
        )
    )
    assert result.page_count == 5
    assert [b.page_number for b in result.blocks] == [1, 3]
    assert [b.kind for b in result.blocks] == [Kind.PARAGRAPH, Kind.TEXT]


def test_empty_after_canonicalization_has_safe_failure(monkeypatch):
    # Keep a defensive failure if a future canonicalization rule erases content.
    monkeypatch.setattr(
        "nexus.documents.application.normalize_document._canonical_text",
        lambda text, kind: "",
    )
    with pytest.raises(DocumentNormalizationError) as exc:
        NormalizeDocument().execute(extracted(line(0, Kind.TEXT, "content")))
    assert exc.value.reason is Failure.EMPTY
    assert str(exc.value) == "Document normalization failed"


@pytest.mark.parametrize("text", ["漢字 Ω", "\ufffd (cid:10)", "a\u00a0b"])
def test_meaningful_unicode_and_unproven_noise_are_retained(text):
    assert (
        NormalizeDocument().execute(extracted(line(0, Kind.TEXT, text))).blocks[0].text
        == text
    )


@pytest.mark.parametrize(
    "limits,blocks",
    [
        ({"max_blocks": 1}, (line(0, Kind.TEXT, "a"), line(1, Kind.TEXT, "b"))),
        ({"max_input_bytes": 2}, (line(0, Kind.TEXT, "漢"),)),
        ({"max_text_bytes": 2}, (line(0, Kind.TEXT, "漢"),)),
    ],
)
def test_each_normalization_bound(limits, blocks):
    with pytest.raises(DocumentNormalizationError) as exc:
        NormalizeDocument(**limits).execute(extracted(*blocks))
    assert exc.value.reason is Failure.RESOURCE_LIMIT


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
@pytest.mark.parametrize("name", ["max_blocks", "max_input_bytes", "max_text_bytes"])
def test_invalid_normalization_limits(name, limit):
    with pytest.raises(ValueError):
        NormalizeDocument(**{name: limit})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"normalizer_id": False},
        {"normalizer_version": " "},
        {"normalizer_id": "x" * 1025},
        {"blocks": []},
        {"blocks": (True,)},
        {"page_count": 1},
    ],
)
def test_normalized_document_validation(kwargs):
    result = NormalizeDocument().execute(extracted(line(0, Kind.TEXT, "content")))
    with pytest.raises(ValueError):
        replace(result, **kwargs)


@pytest.mark.parametrize("path", [[0], (True,), (-1,), (1,), (0,) * 7])
def test_invalid_section_path_types_and_bounds(path):
    block = (
        NormalizeDocument().execute(extracted(line(0, Kind.TEXT, "content"))).blocks[0]
    )
    with pytest.raises(ValueError):
        replace(block, section_path=path)


def test_section_paths_must_reference_meaningful_headings_in_level_order():
    result = NormalizeDocument().execute(
        extracted(
            line(0, Kind.HEADING, "H1", heading_level=1),
            line(1, Kind.HEADING, "H2", heading_level=2),
            line(2, Kind.TEXT, "content"),
        )
    )
    with pytest.raises(ValueError):
        replace(
            result, blocks=(replace(result.blocks[0], text=" "), *result.blocks[1:])
        )
    for path in ((2,), (1, 0), (0, 0)):
        with pytest.raises(ValueError):
            replace(
                result,
                blocks=(
                    *result.blocks[:2],
                    replace(result.blocks[2], section_path=path),
                ),
            )


def test_section_paths_must_preserve_heading_source_order():
    result = NormalizeDocument().execute(
        extracted(
            line(0, Kind.HEADING, "H2", heading_level=2),
            line(1, Kind.HEADING, "H1", heading_level=1),
            line(2, Kind.TEXT, "content"),
        )
    )
    with pytest.raises(ValueError):
        replace(
            result,
            blocks=(
                *result.blocks[:2],
                replace(result.blocks[2], section_path=(1, 0)),
            ),
        )


@pytest.mark.parametrize("markdown", [False, True])
def test_actual_text_extractors_feed_normalization_without_provenance_changes(markdown):
    import asyncio

    from nexus.documents.ports.source import DocumentSource
    from nexus.infrastructure.extraction.text import (
        MarkdownDocumentExtractor,
        TxtDocumentExtractor,
    )

    async def run():
        data = (
            "# Heading\r\n\r\n- Cafe\u0301  Ω\r\n"
            if markdown
            else "Cafe\u0301  Ω\r\n\r\nEnd\r\n"
        ).encode()

        async def content():
            for start in range(0, len(data), 3):
                yield data[start : start + 3]

        source = DocumentSource(
            UUID(int=1),
            "source.md" if markdown else "source.txt",
            "text/markdown" if markdown else "text/plain",
            "etag",
            len(data),
            content(),
        )
        extractor = MarkdownDocumentExtractor() if markdown else TxtDocumentExtractor()
        value = await extractor.extract(source)
        result = NormalizeDocument().execute(value)
        assert result.page_count is None
        assert result.extractor_id == ("nexus.commonmark" if markdown else "nexus.txt")
        assert any("Café  Ω" in block.text for block in result.blocks)
        assert [
            (b.source_block_index, b.start_line, b.end_line) for b in result.blocks
        ] == [(b.index, b.start_line, b.end_line) for b in value.blocks]

    asyncio.run(run())


def test_paragraph_outer_whitespace_only_lines_are_blank_without_trimming_indentation():
    result = NormalizeDocument().execute(
        extracted(line(0, Kind.PARAGRAPH, "\u00a0\n\t\n  body\n\u00a0\n"))
    )
    assert result.blocks[0].text == "  body"


def test_exact_normalization_limits_accept_without_silent_truncation():
    source = extracted(line(0, Kind.TEXT, "漢"), line(1, Kind.TEXT, "Ω"))
    result = NormalizeDocument(
        max_blocks=2, max_input_bytes=5, max_text_bytes=5
    ).execute(source)
    assert [block.text for block in result.blocks] == ["漢", "Ω"]


def test_section_validation_does_not_rescan_heading_text_for_each_reference():
    source = extracted(
        line(0, Kind.HEADING, "Heading", heading_level=1),
        *(line(index, Kind.TEXT, "body") for index in range(1, 1001)),
    )
    result = NormalizeDocument().execute(source)
    calls = []

    class CountedText(str):
        def strip(self, chars=None):
            calls.append(1)
            return super().strip(chars)

    heading = replace(result.blocks[0], text=CountedText(" Heading "))
    value = replace(result, blocks=(heading, *result.blocks[1:]))
    assert value.blocks[-1].section_path == (0,)
    # A small fixed number of checks, independent of section reference count.
    assert len(calls) <= 3
