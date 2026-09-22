"""SQLAlchemy models for MineIntel AI.

Architecture (dual pipeline):

  Document ingestion → OCR/parse → AI extraction → confidence → review → validation → structured DB
  Document → chunking → embeddings → pgvector → RAG

  Structured DB + RAG → Intelligence Layer → Q&A / Analytics / Topics / Reports
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid4())


class DocumentStatus(str, Enum):
    """Lifecycle statuses for ingestion (Phase 2) and later AI review phases."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"  # text extraction done — ready for Phase 3 AI
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    # Phase 1 / Phase 3+ compatibility
    EXTRACTED = "extracted"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class SourceType(str, Enum):
    PDF_PAGE = "pdf_page"
    EXCEL_SHEET = "excel_sheet"
    IMAGE = "image"
    OCR_PAGE = "ocr_page"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class FactStatus(str, Enum):
    EXTRACTED = "extracted"
    HIGH_CONFIDENCE = "high_confidence"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ExtractionJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IndexStatus(str, Enum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    INDEX_FAILED = "index_failed"
    STALE = "stale"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)  # pdf, excel, image
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.UPLOADED.value)
    processing_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    mine_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    document_category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    index_status: Mapped[str] = mapped_column(String(32), default=IndexStatus.NOT_INDEXED.value)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    index_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overall_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    parent_document_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=True, index=True
    )
    replaces_document_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )
    extractions: Mapped[list["Extraction"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    extracted_facts: Mapped[list["ExtractedFact"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    extraction_jobs: Mapped[list["ExtractionJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    reviews: Mapped[list["ReviewItem"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentPage(Base):
    """Page/sheet-level extracted text for citations (Phase 3 RAG/AI)."""

    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # pdf_page | excel_sheet | image | ocr_page
    sheet_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_location: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    content_meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # excel tables, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="pages")
    facts: Mapped[list["ExtractedFact"]] = relationship(back_populates="document_page")


class ExtractionJob(Base):
    """Phase 3 AI extraction job for a completed Phase 2 document."""

    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default=ExtractionJobStatus.PENDING.value)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    facts_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    high_confidence_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="extraction_jobs")
    facts: Mapped[list["ExtractedFact"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class ExtractedFact(Base):
    """Structured mining fact with mandatory source evidence (Phase 3)."""

    __tablename__ = "extracted_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    document_page_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("document_pages.id"), nullable=True, index=True
    )
    job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("extraction_jobs.id"), nullable=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    numeric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # mine / company
    financial_year: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_location: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=FactStatus.EXTRACTED.value)
    is_ocr_source: Mapped[bool] = mapped_column(Boolean, default=False)
    is_calculated: Mapped[bool] = mapped_column(Boolean, default=False)  # derived, not reported
    related_fact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # e.g. calc vs reported
    warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="extracted_facts")
    document_page: Mapped[Optional["DocumentPage"]] = relationship(back_populates="facts")
    job: Mapped[Optional["ExtractionJob"]] = relationship(back_populates="facts")
    review_items: Mapped[list["ReviewItem"]] = relationship(back_populates="extracted_fact")


class Extraction(Base):
    """Legacy Phase 1 extraction stub — prefer ExtractedFact for Phase 3+."""

    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(256), nullable=False)
    field_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    field_type: Mapped[str] = mapped_column(String(64), default="string")  # string, number, date, json
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="extractions")


class DocumentChunk(Base):
    """Text chunks with embeddings for RAG (JSON vectors locally; pgvector-ready)."""

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    document_page_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("document_pages.id"), nullable=True, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), default="document_evidence")  # or verified_fact
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_location: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    document_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # Stored as JSON array for SQLite; Postgres can later use pgvector
    embedding_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")


class ReviewItem(Base):
    """Human-in-the-loop review queue entries (Phase 3 facts)."""

    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    extraction_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("extractions.id"), nullable=True)
    extracted_fact_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("extracted_facts.id"), nullable=True, index=True
    )
    geological_fact_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("geological_facts.id"), nullable=True, index=True
    )
    field_name: Mapped[str] = mapped_column(String(256), nullable=False)
    extracted_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    corrected_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    financial_year: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_document: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=ReviewStatus.PENDING.value)
    reviewer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)  # 1=low, 2=medium, 3=high
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="reviews")
    extracted_fact: Mapped[Optional["ExtractedFact"]] = relationship(back_populates="review_items")


class MiningRecord(Base):
    """Validated structured mining data (post-review warehouse)."""

    __tablename__ = "mining_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("documents.id"), nullable=True)
    mine_name: Mapped[str] = mapped_column(String(256), nullable=False)
    mineral_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    production_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    production_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reporting_period: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_area_ha: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    safety_incidents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    environmental_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    slug: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_citations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    last_extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evidence: Mapped[list["TopicEvidence"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class TopicEvidence(Base):
    """Link a topic to a document page/chunk with provenance."""

    __tablename__ = "topic_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic_id: Mapped[str] = mapped_column(String(36), ForeignKey("topics.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    chunk_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("document_chunks.id"), nullable=True)
    document_page_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("document_pages.id"), nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    document_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    matched_keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    topic: Mapped["Topic"] = relationship(back_populates="evidence")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), default="summary")
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    generated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    source_document_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selected_entities: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selected_periods: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    output_format: Mapped[str] = mapped_column(String(32), default="html")
    provenance: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """Persisted AI assistant messages (intelligence layer)."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConflictStatus(str, Enum):
    DETECTED = "detected"
    REVIEW_REQUIRED = "review_required"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ConflictType(str, Enum):
    CONTRADICTION = "contradiction"
    DISCREPANCY = "discrepancy"
    ENTITY_MATCH_REVIEW = "entity_match_review"
    UNIT_REVIEW = "unit_review"


class ConflictSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ValidationConflict(Base):
    """Cross-document / reported-vs-calculated validation conflict (Phase 5)."""

    __tablename__ = "validation_conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    conflict_type: Mapped[str] = mapped_column(String(64), default=ConflictType.CONTRADICTION.value)
    entity_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    period: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=ConflictStatus.REVIEW_REQUIRED.value, index=True)
    severity: Mapped[str] = mapped_column(String(32), default=ConflictSeverity.MEDIUM.value)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    selected_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evidence_items: Mapped[list["ConflictEvidence"]] = relationship(
        back_populates="conflict", cascade="all, delete-orphan", order_by="ConflictEvidence.created_at"
    )


class ConflictEvidence(Base):
    """One side of a validation conflict with full source traceability."""

    __tablename__ = "conflict_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conflict_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("validation_conflicts.id"), nullable=False, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("documents.id"), nullable=True)
    document_page_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("document_pages.id"), nullable=True
    )
    extracted_fact_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("extracted_facts.id"), nullable=True, index=True
    )
    document_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_location: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    numeric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    normalized_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_calculated: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # A / B / reported / calculated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conflict: Mapped["ValidationConflict"] = relationship(back_populates="evidence_items")


class UserRole(str, Enum):
    """Active roles: admin | user. Legacy analyst/reviewer normalized via auth.deps."""

    ADMIN = "admin"
    USER = "user"
    # Deprecated — kept for DB read compatibility until migrated
    ANALYST = "analyst"
    REVIEWER = "reviewer"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class User(Base):
    """Local authentication users (Phase 7 RBAC)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.USER.value, index=True)
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.ACTIVE.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FactCorrectionHistory(Base):
    """Immutable record of AI extraction → human correction (Phase 7)."""

    __tablename__ = "fact_correction_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    extracted_fact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("extracted_facts.id"), nullable=False, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("documents.id"), nullable=True)
    review_item_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("review_items.id"), nullable=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    original_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeologicalFact(Base):
    """Geological / exploration fact with mandatory source provenance (G1/G2)."""

    __tablename__ = "geological_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    document_page_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("document_pages.id"), nullable=True, index=True
    )
    domain: Mapped[str] = mapped_column(String(64), default="geological", index=True)
    metric_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    borehole_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    seam_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    # named | uncorrelated | unnamed — uncorrelated/unnamed have no invented identifier
    seam_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    depth: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    depth_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    depth_normalized_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thickness: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    thickness_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    thickness_normalized_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Range support (min/max when source text states a range) — single-point facts leave these null
    thickness_min: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    thickness_max: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    thickness_min_normalized_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thickness_max_normalized_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    depth_min: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    depth_max: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    depth_min_normalized_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    depth_max_normalized_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Original / qualifier representation (G2) — never lose source form
    original_value: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    original_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    value_qualifier: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # >, <, ~, range
    lithology: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    geological_formation: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    geological_structure: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    coal_quality_parameter: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    coal_quality_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    coal_quality_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_location: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=FactStatus.EXTRACTED.value, index=True)
    # Human correction history (G2) — never silently overwrite provenance
    original_extracted_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    corrected_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    corrected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fact_version: Mapped[int] = mapped_column(Integer, default=1)
    warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    table_context: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
