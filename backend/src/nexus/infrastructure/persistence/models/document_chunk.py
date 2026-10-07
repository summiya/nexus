"""One immutable set of ordered chunks, owned by a Document and its tenant."""

from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nexus.infrastructure.persistence.base import Base


class DocumentChunkSet(Base):
    __tablename__ = "document_chunk_sets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.id", "documents.organization_id"],
            name="fk_document_chunk_sets_document_organization",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "document_id",
            "organization_id",
            name="uq_document_chunk_sets_document_organization",
        ),
        CheckConstraint("chunk_count > 0", name="ck_document_chunk_sets_count"),
        CheckConstraint(
            "preferred_chunk_bytes > 0 AND max_chunk_bytes >= preferred_chunk_bytes AND max_source_contributions > 0",
            name="ck_document_chunk_sets_settings",
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count > 0", name="ck_document_chunk_sets_pages"
        ),
        CheckConstraint(
            "source_entity_tag ~ '\\S' AND extractor_id ~ '\\S' AND extractor_version ~ '\\S' AND normalizer_id ~ '\\S' AND normalizer_version ~ '\\S' AND segmenter_id ~ '\\S' AND segmenter_version ~ '\\S'",
            name="ck_document_chunk_sets_metadata",
        ),
    )

    document_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_entity_tag: Mapped[str] = mapped_column(String(1024), nullable=False)
    extractor_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalizer_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(1024), nullable=False)
    segmenter_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    segmenter_version: Mapped[str] = mapped_column(String(1024), nullable=False)
    preferred_chunk_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_chunk_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_source_contributions: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["document_chunk_sets.document_id", "document_chunk_sets.organization_id"],
            name="fk_document_chunks_set_organization",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_index"
        ),
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index"),
        CheckConstraint("text ~ '\\S'", name="ck_document_chunks_text"),
        CheckConstraint(
            "kind IN ('text', 'paragraph', 'list', 'code', 'raw', 'heading')",
            name="ck_document_chunks_kind",
        ),
        CheckConstraint(
            "cardinality(section_path) <= 6", name="ck_document_chunks_section_path"
        ),
        CheckConstraint(
            "CASE WHEN jsonb_typeof(contributions) = 'array' THEN jsonb_array_length(contributions) > 0 ELSE false END",
            name="ck_document_chunks_contributions",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    section_path: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    contributions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
