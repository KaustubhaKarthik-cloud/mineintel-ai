"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Documents ──────────────────────────────────────────────

class DocumentBase(BaseModel):
    filename: str
    file_type: str
    mine_name: Optional[str] = None
    document_category: Optional[str] = None


class DocumentPageOut(BaseModel):
    id: str
    page_number: int
    text: str
    source_type: str
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    char_count: int = 0
    content_meta: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    mime_type: Optional[str] = None
    status: str
    processing_stage: Optional[str] = None
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    version: int = 1
    is_scanned: bool = False
    mine_name: Optional[str] = None
    document_category: Optional[str] = None
    page_count: int = 0
    overall_confidence: Optional[float] = None
    ocr_completed: bool = False
    extraction_completed: bool = False
    embedding_completed: bool = False
    index_status: str = "not_indexed"
    indexed_at: Optional[datetime] = None
    index_error: Optional[str] = None
    error_message: Optional[str] = None
    uploaded_by: Optional[str] = None
    created_at: Optional[datetime] = None
    upload_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentDetailOut(DocumentOut):
    pages: list[DocumentPageOut] = []
    meta: Optional[dict[str, Any]] = None
    facts: list["ExtractedFactOut"] = []
    latest_extraction_job: Optional["ExtractionJobOut"] = None
    conflicts: list["ValidationConflictOut"] = []


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentOut]


class ProcessingStatusOut(BaseModel):
    id: str
    status: str
    processing_stage: Optional[str] = None
    error_message: Optional[str] = None
    page_count: int = 0
    is_scanned: bool = False
    ocr_completed: bool = False
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None


# ── Phase 3 facts / extraction ─────────────────────────────

class ExtractedFactOut(BaseModel):
    id: str
    document_id: str
    document_page_id: Optional[str] = None
    field_name: str
    value: Optional[str] = None
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    entity_name: Optional[str] = None
    financial_year: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    evidence_text: Optional[str] = None
    confidence_score: float
    status: str
    is_ocr_source: bool = False
    is_calculated: bool = False
    related_fact_id: Optional[str] = None
    warnings: Optional[list[Any]] = None
    created_at: Optional[datetime] = None
    has_conflict: bool = False
    conflict_ids: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ExtractionJobOut(BaseModel):
    id: str
    document_id: str
    status: str
    provider: Optional[str] = None
    facts_count: int = 0
    review_count: int = 0
    high_confidence_count: int = 0
    warnings: Optional[list[Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ExtractionSummaryOut(BaseModel):
    job: ExtractionJobOut
    facts: list[ExtractedFactOut] = []


class BatchExtractRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list)


class BatchExtractResponse(BaseModel):
    results: list[dict[str, Any]]


# ── Review ─────────────────────────────────────────────────

class ReviewItemOut(BaseModel):
    id: str
    document_id: str
    document_name: Optional[str] = None
    extracted_fact_id: Optional[str] = None
    field_name: str
    extracted_value: Optional[str] = None
    corrected_value: Optional[str] = None
    original_unit: Optional[str] = None
    corrected_unit: Optional[str] = None
    entity_name: Optional[str] = None
    financial_year: Optional[str] = None
    evidence_text: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    source_document: Optional[str] = None
    confidence: float
    status: str
    priority: int = 1
    mine_name: Optional[str] = None
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReviewAction(BaseModel):
    action: str = Field(..., description="approve | reject | correct")
    corrected_value: Optional[str] = None
    corrected_unit: Optional[str] = None
    entity_name: Optional[str] = None
    financial_year: Optional[str] = None
    review_notes: Optional[str] = None
    reviewer: str = "demo_user"


class ReviewListResponse(BaseModel):
    total: int
    pending: int
    items: list[ReviewItemOut]


# ── Chat / AI Assistant ────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None


class ChatSource(BaseModel):
    document_id: str
    document_name: str
    snippet: str
    relevance: float
    page: Optional[int] = None
    sheet_name: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    sources: list[ChatSource] = []
    query_type: Optional[str] = None
    structured_evidence: list[dict[str, Any]] = Field(default_factory=list)
    rag_evidence: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    chart: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)


class AssistantQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    history: list[dict[str, str]] = Field(default_factory=list)


class AssistantChartRequest(BaseModel):
    entity: Optional[str] = None
    metric: str = "production"
    question: Optional[str] = None
    session_id: Optional[str] = None


# ── Analytics ──────────────────────────────────────────────

class AnalyticsKPI(BaseModel):
    label: str
    value: str | int | float
    change: Optional[float] = None
    unit: Optional[str] = None


class ChartSeries(BaseModel):
    name: str
    data: list[dict[str, Any]]


class AnalyticsResponse(BaseModel):
    kpis: list[AnalyticsKPI]
    production_by_mineral: list[dict[str, Any]]
    documents_by_status: list[dict[str, Any]]
    monthly_uploads: list[dict[str, Any]]
    confidence_distribution: list[dict[str, Any]]
    top_mines: list[dict[str, Any]]


# ── Dashboard ──────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_documents: int
    pending_review: int
    approved_records: int
    avg_confidence: float
    processing_queue: int
    topics_tracked: int
    reports_generated: int
    recent_documents: list[DocumentOut]
    recent_activity: list[dict[str, Any]]
    pipeline_status: dict[str, Any]


# ── Health ─────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    app: str
    demo_mode: bool
    database: str
    version: str = "0.1.0"


# ── Phase 4 search / indexing ──────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    document_id: Optional[str] = None
    include_context: bool = True


class SearchResultItem(BaseModel):
    text: str
    score: float
    document: Optional[str] = None
    document_id: str
    page: Optional[int] = None
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    content_type: str = "document_evidence"
    document_version: int = 1
    chunk_id: str
    has_conflict: bool = False
    conflict_ids: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    context: Optional[str] = None


class IndexResultOut(BaseModel):
    document_id: str
    index_status: str
    embedding_completed: bool
    indexed_at: Optional[datetime] = None
    chunk_count: int = 0
    index_error: Optional[str] = None


# ── Phase 5 validation / conflicts ─────────────────────────

class ConflictEvidenceOut(BaseModel):
    id: str
    document_id: Optional[str] = None
    document_page_id: Optional[str] = None
    extracted_fact_id: Optional[str] = None
    document_name: Optional[str] = None
    document_version: int = 1
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    numeric_value: Optional[float] = None
    normalized_value: Optional[float] = None
    evidence_text: Optional[str] = None
    is_calculated: bool = False
    label: Optional[str] = None

    model_config = {"from_attributes": True}


class ValidationConflictOut(BaseModel):
    id: str
    fingerprint: str
    conflict_type: str
    entity_name: Optional[str] = None
    field_name: str
    period: Optional[str] = None
    status: str
    severity: str
    description: str
    selected_value: Optional[str] = None
    selected_unit: Optional[str] = None
    resolution_reason: Optional[str] = None
    reviewer: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    evidence: list[ConflictEvidenceOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ValidationRunResponse(BaseModel):
    facts_scanned: int
    conflicts_detected: int
    created: int
    refreshed: int
    unchanged_terminal: int = 0
    auto_cleared: int = 0


class ValidationStatsOut(BaseModel):
    facts: int
    validated: int
    review_required: int
    conflicts: int
    resolved: int
    confirmed: int = 0
    dismissed: int = 0
    total_conflict_records: int = 0


class ConflictListResponse(BaseModel):
    total: int
    items: list[ValidationConflictOut]


class ConflictResolveRequest(BaseModel):
    selected_value: str = Field(..., min_length=1, max_length=512)
    selected_unit: Optional[str] = Field(default=None, max_length=64)
    reason: Optional[str] = Field(default=None, max_length=2000)


class ConflictActionRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)
    notes: Optional[str] = Field(default=None, max_length=2000)
