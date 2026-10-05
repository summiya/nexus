import asyncio
from dataclasses import replace
from threading import Event
from uuid import UUID

import pytest

from nexus.documents.domain import ExtractedBlockKind as Kind
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionFailure as Failure,
)
from nexus.documents.ports.source import (
    DocumentSource,
    DocumentSourceError,
    DocumentSourceFailure,
)
from nexus.infrastructure.extraction import text as adapters
from nexus.infrastructure.extraction.text import (
    MarkdownDocumentExtractor,
    TxtDocumentExtractor,
)


def source(data, *, width=4, content=None):
    async def stream():
        for start in range(0, len(data), width):
            yield data[start : start + width]

    return DocumentSource(
        UUID(int=1),
        "example.txt",
        "text/plain",
        "opaque-version",
        len(data),
        stream() if content is None else content,
    )


def extract(extractor, data, **kwargs):
    return asyncio.run(extractor.extract(source(data, **kwargs)))


@pytest.mark.parametrize("width", [1, 2, 3, 7, 100])
def test_txt_is_deterministic_across_utf8_bom_and_newline_boundaries(width):
    data = "\ufeffα\r\n \r\n\rβ\nlast".encode()
    result = extract(TxtDocumentExtractor(), data, width=width)
    assert [b.text for b in result.blocks] == ["α", " ", "", "β", "last"]
    assert [(b.index, b.kind, b.start_line, b.end_line) for b in result.blocks] == [
        (i, Kind.TEXT, i + 1, i + 2) for i in range(5)
    ]
    assert all(
        b.heading_level is None and b.list_item is None and b.quote_depth == 0
        for b in result.blocks
    )
    assert result == extract(TxtDocumentExtractor(), data, width=1)
    assert result.source_file_public_id == UUID(int=1)
    assert result.source_entity_tag == "opaque-version"
    assert (result.extractor_id, result.extractor_version) == (
        adapters.TXT_EXTRACTOR_ID,
        adapters.TXT_EXTRACTOR_VERSION,
    )


@pytest.mark.parametrize(
    "data,texts",
    [
        (b"x\n", ["x"]),
        (b"x\n\n", ["x", ""]),
        (b"# title\n- item", ["# title", "- item"]),
        (b"x\r\n\r\n", ["x", ""]),
    ],
)
def test_txt_physical_lines_do_not_invent_structure(data, texts):
    assert [
        b.text for b in extract(TxtDocumentExtractor(), data, width=1).blocks
    ] == texts


@pytest.mark.parametrize("extractor", [TxtDocumentExtractor, MarkdownDocumentExtractor])
@pytest.mark.parametrize("data", [b"", b" \t\r\n", b"\xef\xbb\xbf"])
def test_empty_documents_fail_safely(extractor, data):
    with pytest.raises(DocumentExtractionError) as exc:
        extract(extractor(), data, width=1)
    assert exc.value.reason is Failure.EMPTY
    assert str(exc.value) == "Document extraction failed"


@pytest.mark.parametrize("extractor", [TxtDocumentExtractor, MarkdownDocumentExtractor])
@pytest.mark.parametrize(
    "data", [b"private\xff", b"private\x00", b"\xe2\x82", b"\xff\xfea\x00"]
)
def test_malformed_input_does_not_leak_content(extractor, data):
    with pytest.raises(DocumentExtractionError) as exc:
        extract(extractor(), data, width=1)
    assert exc.value.reason is Failure.MALFORMED
    assert "private" not in str(exc.value)


MARKDOWN = (
    "Title\n=====\n\n# Head *em*\n\n3. first\n\n   second paragraph\n\n"
    "   - nested\n\n   after nested\n\n4. second\n\n> quoted\n>\n"
    "> ```py\n> x = 1\n> ```\n\n---\n\n<div>literal</div>\n"
)


@pytest.mark.parametrize("width", [1, 3, 11, 1000])
def test_markdown_preserves_logical_structure_order_and_line_ranges(width):
    result = extract(MarkdownDocumentExtractor(), MARKDOWN.encode(), width=width)
    blocks = result.blocks
    assert [(b.kind, b.text, b.start_line, b.end_line) for b in blocks] == [
        (Kind.HEADING, "Title", 1, 3),
        (Kind.HEADING, "Head em", 4, 5),
        (Kind.PARAGRAPH, "first", 6, 7),
        (Kind.PARAGRAPH, "second paragraph", 8, 9),
        (Kind.PARAGRAPH, "nested", 10, 11),
        (Kind.PARAGRAPH, "after nested", 12, 13),
        (Kind.PARAGRAPH, "second", 14, 15),
        (Kind.PARAGRAPH, "quoted", 16, 17),
        (Kind.CODE, "x = 1\n", 18, 21),
        (Kind.THEMATIC_BREAK, "", 22, 23),
        (Kind.RAW, "<div>literal</div>\n", 24, 25),
    ]
    assert [b.index for b in blocks] == list(range(len(blocks)))
    assert [b.heading_level for b in blocks[:2]] == [1, 1]
    item = blocks[2].list_item
    assert (
        item.list_start_line,
        item.item_start_line,
        item.depth,
        item.ordered,
        item.ordinal,
    ) == (6, 6, 1, True, 3)
    assert blocks[3].list_item == item == blocks[5].list_item
    nested = blocks[4].list_item
    assert (
        nested.list_start_line,
        nested.item_start_line,
        nested.depth,
        nested.ordered,
        nested.ordinal,
    ) == (10, 10, 2, False, None)
    assert blocks[6].list_item.ordinal == 4
    assert blocks[6].list_item.item_start_line == 14
    assert [b.quote_depth for b in blocks[7:9]] == [1, 1]
    assert result == extract(MarkdownDocumentExtractor(), MARKDOWN.encode(), width=1)
    assert (result.extractor_id, result.extractor_version) == (
        adapters.MARKDOWN_EXTRACTOR_ID,
        adapters.MARKDOWN_EXTRACTOR_VERSION,
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_markdown_logical_inline_content_and_provenance(newline):
    data = newline.join(
        [
            "## α **bold** &amp; `code` [label](https://invalid)",
            "",
            "> > text  ",
            "> > next ![alt *em*](https://invalid)",
        ]
    ).encode()
    blocks = extract(MarkdownDocumentExtractor(), data, width=1).blocks
    assert [(b.text, b.start_line, b.end_line) for b in blocks] == [
        ("α bold & code label", 1, 2),
        ("text\nnext alt em", 3, 5),
    ]
    assert blocks[0].heading_level == 2
    assert blocks[1].quote_depth == 2


def test_commonmark_valid_incomplete_syntax_and_indented_code_are_retained():
    result = extract(
        MarkdownDocumentExtractor(),
        b"    code\n\n[unclosed *literal\n\n```\nunfinished",
    )
    assert [b.text for b in result.blocks] == [
        "code\n",
        "[unclosed *literal",
        "unfinished",
    ]
    assert [b.kind for b in result.blocks] == [Kind.CODE, Kind.PARAGRAPH, Kind.CODE]


def test_ordered_list_zero_start_is_preserved():
    blocks = extract(MarkdownDocumentExtractor(), b"0. zero\n1. one").blocks
    assert [b.list_item.ordinal for b in blocks] == [0, 1]


@pytest.mark.parametrize("extractor", [TxtDocumentExtractor, MarkdownDocumentExtractor])
def test_size_and_emitted_block_bounds(extractor):
    assert extract(extractor(max_bytes=3, max_blocks=1), b"abc").blocks[0].text == "abc"
    with pytest.raises(DocumentExtractionError) as exc:
        extract(extractor(max_bytes=2), b"abc")
    assert exc.value.reason is Failure.RESOURCE_LIMIT
    with pytest.raises(DocumentExtractionError) as exc:
        extract(extractor(max_blocks=1), b"a\n\nb")
    assert exc.value.reason is Failure.RESOURCE_LIMIT


@pytest.mark.parametrize("extractor", [TxtDocumentExtractor, MarkdownDocumentExtractor])
def test_actual_input_bound_is_enforced_even_if_declared_size_is_small(extractor):
    async def run():
        with pytest.raises(DocumentExtractionError) as exc:
            await extractor(max_bytes=2).extract(
                replace(source(b"abc", width=1), expected_size_bytes=1)
            )
        assert exc.value.reason is Failure.RESOURCE_LIMIT

    asyncio.run(run())


def test_markdown_refuses_depth_truncation():
    with pytest.raises(DocumentExtractionError) as exc:
        extract(
            MarkdownDocumentExtractor(), ("safe\n\n" + "> " * 40 + "hidden").encode()
        )
    assert exc.value.reason is Failure.RESOURCE_LIMIT


@pytest.mark.parametrize("extractor", [TxtDocumentExtractor, MarkdownDocumentExtractor])
def test_source_failure_at_eof_prevents_returning_output(extractor):
    async def stream():
        yield b"text"
        raise DocumentSourceError(DocumentSourceFailure.CHANGED)

    with pytest.raises(DocumentSourceError) as exc:
        extract(extractor(), b"text", content=stream())
    assert exc.value.reason is DocumentSourceFailure.CHANGED


def test_parser_failure_is_safe(monkeypatch):
    def fail(*args):
        raise RuntimeError("private parser content")

    monkeypatch.setattr(adapters.MarkdownIt, "parse", fail)
    with pytest.raises(DocumentExtractionError) as exc:
        extract(MarkdownDocumentExtractor(), b"text")
    assert exc.value.reason is Failure.PARSER_FAILURE
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("parser_fails", [False, True])
def test_parser_runs_off_loop_and_cancellation_waits_for_settlement(
    monkeypatch, parser_fails
):
    started, release, settled = Event(), Event(), Event()
    original = adapters._parse_markdown

    def blocking(*args):
        started.set()
        try:
            assert release.wait(5)
            if parser_fails:
                raise RuntimeError("private failure during cancellation")
            return original(*args)
        finally:
            settled.set()

    monkeypatch.setattr(adapters, "_parse_markdown", blocking)

    async def run():
        task = asyncio.create_task(MarkdownDocumentExtractor().extract(source(b"text")))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert settled.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("extractor", [TxtDocumentExtractor, MarkdownDocumentExtractor])
@pytest.mark.parametrize(
    "kwargs", [{"max_bytes": 0}, {"max_blocks": 0}, {"max_bytes": True}]
)
def test_limits_require_positive_integers(extractor, kwargs):
    with pytest.raises(ValueError):
        extractor(**kwargs)
