"""Bounded UTF-8 TXT/CommonMark extraction; parser types stay here."""

import asyncio
import codecs
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

from nexus.documents.domain.extracted_document import (
    ExtractedBlock,
    ExtractedBlockKind,
    ExtractedDocument,
    ExtractedListItem,
)
from nexus.documents.ports.extraction import (
    DocumentExtractionError,
    DocumentExtractionFailure,
)
from nexus.documents.ports.source import DocumentSource

TXT_EXTRACTOR_ID = "nexus.txt"
TXT_EXTRACTOR_VERSION = "1"
MARKDOWN_EXTRACTOR_ID = "nexus.commonmark"
MARKDOWN_EXTRACTOR_VERSION = "1"
DEFAULT_MAX_EXTRACTION_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_EXTRACTION_BLOCKS = 50_000
_MARKDOWN_MAX_NESTING = 32
_NEWLINE = re.compile(r"\r\n|\r|\n")


def _validate_limits(max_bytes: int, max_blocks: int) -> None:
    if any(type(value) is not int or value <= 0 for value in (max_bytes, max_blocks)):
        raise ValueError("Invalid extraction limits")


async def _decode(source: DocumentSource, max_bytes: int) -> AsyncIterator[str]:
    if source.expected_size_bytes > max_bytes:
        raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
    decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
    count = 0
    try:
        async for chunk in source.content:
            count += len(chunk)
            if count > max_bytes:
                raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
            text = decoder.decode(chunk)
            if "\x00" in text:
                raise DocumentExtractionError(DocumentExtractionFailure.MALFORMED)
            yield text
        yield decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise DocumentExtractionError(DocumentExtractionFailure.MALFORMED) from exc


async def _lines(source: DocumentSource, max_bytes: int) -> AsyncIterator[str]:
    fragments: list[str] = []
    trailing_cr = False
    async for text in _decode(source, max_bytes):
        if not text:
            continue
        if trailing_cr and text.startswith("\n"):
            text = text[1:]
        trailing_cr = text.endswith("\r")
        start = 0
        for match in _NEWLINE.finditer(text):
            fragments.append(text[start : match.start()])
            yield "".join(fragments)
            fragments.clear()
            start = match.end()
        if start < len(text):
            fragments.append(text[start:])
    if fragments:
        yield "".join(fragments)


def _result(
    source: DocumentSource,
    extractor_id: str,
    version: str,
    blocks: list[ExtractedBlock],
) -> ExtractedDocument:
    if not any(block.text.strip() for block in blocks):
        raise DocumentExtractionError(DocumentExtractionFailure.EMPTY)
    return ExtractedDocument(
        source.source_file_public_id,
        source.entity_tag,
        extractor_id,
        version,
        tuple(blocks),
    )


class TxtDocumentExtractor:
    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_EXTRACTION_BYTES,
        max_blocks: int = DEFAULT_MAX_EXTRACTION_BLOCKS,
    ) -> None:
        _validate_limits(max_bytes, max_blocks)
        self._max_bytes = max_bytes
        self._max_blocks = max_blocks

    async def extract(self, source: DocumentSource) -> ExtractedDocument:
        blocks: list[ExtractedBlock] = []
        async for line in _lines(source, self._max_bytes):
            if len(blocks) >= self._max_blocks:
                raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
            index = len(blocks)
            blocks.append(
                ExtractedBlock(
                    index, ExtractedBlockKind.TEXT, line, index + 1, index + 2
                )
            )
        return _result(source, TXT_EXTRACTOR_ID, TXT_EXTRACTOR_VERSION, blocks)


class MarkdownDocumentExtractor:
    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_EXTRACTION_BYTES,
        max_blocks: int = DEFAULT_MAX_EXTRACTION_BLOCKS,
    ) -> None:
        _validate_limits(max_bytes, max_blocks)
        self._max_bytes = max_bytes
        self._max_blocks = max_blocks

    async def extract(self, source: DocumentSource) -> ExtractedDocument:
        fragments = [text async for text in _decode(source, self._max_bytes) if text]
        text = "".join(fragments)
        fragments.clear()
        task = asyncio.create_task(
            asyncio.to_thread(_parse_markdown, text, self._max_bytes, self._max_blocks)
        )
        try:
            blocks = await asyncio.shield(task)
        except asyncio.CancelledError:
            # A Python parser thread cannot be interrupted. Retain the slot until
            # it settles, including if another cancellation arrives meanwhile.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:  # noqa: BLE001 - Preserve cancellation after any parser failure.
                    break
            if not task.cancelled():
                task.exception()
            raise
        return _result(
            source, MARKDOWN_EXTRACTOR_ID, MARKDOWN_EXTRACTOR_VERSION, blocks
        )


@dataclass
class _ListState:
    start_line: int
    ordered: bool
    next_ordinal: int
    item: ExtractedListItem | None = None


def _line_range(token: Token) -> tuple[int, int]:
    if token.map is None:
        raise DocumentExtractionError(DocumentExtractionFailure.PARSER_FAILURE)
    return token.map[0] + 1, token.map[1] + 1


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    pending = list(reversed(token.children or []))
    while pending:
        child = pending.pop()
        if child.type == "image":
            pending.extend(reversed(child.children or []))
        elif child.type in {"text", "code_inline", "html_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
    return "".join(parts)


def _parse_markdown(text: str, max_bytes: int, max_blocks: int) -> list[ExtractedBlock]:
    try:
        parser = MarkdownIt("commonmark", {"maxNesting": _MARKDOWN_MAX_NESTING})
        return _map_markdown(parser.parse(text), max_bytes, max_blocks)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError(DocumentExtractionFailure.PARSER_FAILURE) from exc


def _map_markdown(
    tokens: list[Token], max_bytes: int, max_blocks: int
) -> list[ExtractedBlock]:
    blocks: list[ExtractedBlock] = []
    lists: list[_ListState] = []
    quote_depth = 0
    content_open: Token | None = None
    text_bytes = 0
    for token in tokens:
        # Refuse parser depth truncation rather than returning partial content.
        if token.nesting == 1 and token.level >= _MARKDOWN_MAX_NESTING - 1:
            raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            start, _ = _line_range(token)
            ordinal = token.attrGet("start")
            lists.append(
                _ListState(
                    start,
                    token.type == "ordered_list_open",
                    int(1 if ordinal is None else ordinal),
                )
            )
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif token.type == "list_item_open":
            state = lists[-1]
            start, _ = _line_range(token)
            state.item = ExtractedListItem(
                state.start_line,
                start,
                len(lists),
                state.ordered,
                state.next_ordinal if state.ordered else None,
            )
            state.next_ordinal += 1
        elif token.type == "list_item_close":
            lists[-1].item = None
        elif token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth -= 1
        elif token.type in {"paragraph_open", "heading_open"}:
            content_open = token
        elif token.type in {"paragraph_close", "heading_close"}:
            content_open = None
        else:
            block = _content_block(
                token,
                content_open,
                len(blocks),
                lists[-1].item if lists else None,
                quote_depth,
            )
            if block is None:
                continue
            text_bytes += len(block.text.encode("utf-8"))
            if len(blocks) >= max_blocks or text_bytes > max_bytes:
                raise DocumentExtractionError(DocumentExtractionFailure.RESOURCE_LIMIT)
            blocks.append(block)
    return blocks


def _content_block(
    token: Token,
    content_open: Token | None,
    index: int,
    list_item: ExtractedListItem | None,
    quote_depth: int,
) -> ExtractedBlock | None:
    heading_level = None
    if token.type == "inline" and content_open is not None:
        heading = content_open.type == "heading_open"
        kind = ExtractedBlockKind.HEADING if heading else ExtractedBlockKind.PARAGRAPH
        heading_level = int(content_open.tag[1:]) if heading else None
        text = _inline_text(token)
        start, end = _line_range(content_open)
    elif token.type in {"fence", "code_block", "html_block", "hr"}:
        kind = {
            "fence": ExtractedBlockKind.CODE,
            "code_block": ExtractedBlockKind.CODE,
            "html_block": ExtractedBlockKind.RAW,
            "hr": ExtractedBlockKind.THEMATIC_BREAK,
        }[token.type]
        text = token.content
        start, end = _line_range(token)
    else:
        return None
    return ExtractedBlock(
        index, kind, text, start, end, heading_level, list_item, quote_depth
    )
