export interface DocumentPage {
  id: string
  page_number: number
  text: string
  source_type: string
  sheet_name?: string | null
  source_location?: string | null
  char_count: number
  content_meta?: {
    columns?: string[]
    row_count?: number
    rows?: Record<string, string>[]
  } | null
}

export interface ExtractedFact {
  id: string
  document_id: string
  document_page_id?: string | null
  field_name: string
  value?: string | null
  numeric_value?: number | null
  unit?: string | null
  entity_name?: string | null
  financial_year?: string | null
  page_number?: number | null
  sheet_name?: string | null
  source_location?: string | null
  evidence_text?: string | null
  confidence_score: number
  status: string
  is_ocr_source?: boolean
  is_calculated?: boolean
  related_fact_id?: string | null
  warnings?: string[] | null
  created_at?: string | null
  has_conflict?: boolean
  conflict_ids?: string[]
}

export interface ConflictEvidence {
  id: string
  document_id?: string | null
  document_page_id?: string | null
  extracted_fact_id?: string | null
  document_name?: string | null
  document_version?: number
  page_number?: number | null
  sheet_name?: string | null
  source_location?: string | null
  value?: string | null
  unit?: string | null
  numeric_value?: number | null
  evidence_text?: string | null
  is_calculated?: boolean
  label?: string | null
}

export interface ValidationConflict {
  id: string
  fingerprint: string
  conflict_type: string
  entity_name?: string | null
  field_name: string
  period?: string | null
  status: string
  severity: string
  description: string
  selected_value?: string | null
  selected_unit?: string | null
  resolution_reason?: string | null
  reviewer?: string | null
  resolved_at?: string | null
  created_at?: string | null
  evidence: ConflictEvidence[]
}

export interface ValidationStats {
  facts: number
  validated: number
  review_required: number
  conflicts: number
  resolved: number
  confirmed?: number
  dismissed?: number
  total_conflict_records?: number
}

export interface ExtractionJob {
  id: string
  document_id: string
  status: string
  provider?: string | null
  facts_count: number
  review_count: number
  high_confidence_count: number
  warnings?: string[] | null
  error_message?: string | null
  started_at?: string | null
  completed_at?: string | null
}

export interface DocumentItem {
  id: string
  filename: string
  original_filename: string
  file_type: string
  file_size: number
  mime_type?: string | null
  status: string
  processing_stage?: string | null
  processing_started_at?: string | null
  processing_completed_at?: string | null
  version?: number
  is_scanned?: boolean
  mine_name?: string | null
  document_category?: string | null
  page_count: number
  overall_confidence?: number | null
  ocr_completed: boolean
  extraction_completed: boolean
  embedding_completed: boolean
  index_status?: string
  indexed_at?: string | null
  index_error?: string | null
  error_message?: string | null
  uploaded_by?: string | null
  created_at?: string | null
  upload_date?: string | null
}

export interface DocumentDetail extends DocumentItem {
  pages: DocumentPage[]
  meta?: Record<string, unknown> | null
  facts?: ExtractedFact[]
  latest_extraction_job?: ExtractionJob | null
  conflicts?: ValidationConflict[]
}

export interface ReviewItem {
  id: string
  document_id: string
  document_name?: string | null
  extracted_fact_id?: string | null
  field_name: string
  extracted_value?: string | null
  corrected_value?: string | null
  original_unit?: string | null
  corrected_unit?: string | null
  entity_name?: string | null
  financial_year?: string | null
  evidence_text?: string | null
  page_number?: number | null
  sheet_name?: string | null
  source_document?: string | null
  confidence: number
  status: string
  priority: number
  mine_name?: string | null
  reviewer?: string | null
  review_notes?: string | null
  created_at?: string | null
  reviewed_at?: string | null
}

export interface ChatSource {
  document_id: string
  document_name: string
  snippet: string
  relevance: number
  page?: number | null
  sheet_name?: string | null
}

export interface AssistantChart {
  type: string
  title?: string
  x_axis?: string
  y_axis?: string
  data: Array<{ year: string; value: number; unit?: string; source?: string; page?: number }>
  provenance?: Array<Record<string, unknown>>
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: ChatSource[]
  query_type?: string
  structured_evidence?: Array<Record<string, unknown>>
  rag_evidence?: Array<Record<string, unknown>>
  conflicts?: Array<Record<string, unknown>>
  chart?: AssistantChart | null
  warnings?: string[]
}

export interface DashboardStats {
  total_documents: number
  pending_review: number
  approved_records: number
  avg_confidence: number
  processing_queue: number
  topics_tracked: number
  reports_generated: number
  recent_documents: DocumentItem[]
  recent_activity: Array<{
    id: string
    action: string
    detail: string
    actor: string
    timestamp: string
  }>
  pipeline_status: Record<string, string>
}

export interface AnalyticsData {
  kpis: Array<{
    label: string
    value: string | number
    change?: number | null
    unit?: string | null
  }>
  production_by_mineral: Array<{ mineral: string; production: number }>
  documents_by_status: Array<{ status: string; count: number }>
  monthly_uploads: Array<{ month: string; uploads: number }>
  confidence_distribution: Array<{ bucket: string; count: number }>
  top_mines: Array<{ mine: string; documents: number; production: number }>
}

export interface AnalyticsProvenance {
  entity?: string
  metric?: string
  period?: string | null
  value?: number
  unit?: string | null
  document_id?: string
  document_name?: string
  page?: number | null
  sheet_name?: string | null
  fact_id?: string
  status?: string
}

export interface AnalyticsTrendResponse {
  chart_type: string
  entity?: string | null
  metric: string
  unit?: string | null
  data: Array<Record<string, unknown>>
  provenance: AnalyticsProvenance[]
  warnings: string[]
  insufficient: boolean
  message?: string | null
  source_documents?: string[]
  filters?: Record<string, unknown>
}

export interface ActualVsTargetResponse {
  entity: string
  period?: string | null
  actual?: number | null
  target?: number | null
  achievement_percentage?: number | null
  unit?: string | null
  chart_type: string
  data: Array<{ label: string; value: number; unit?: string }>
  series?: Array<Record<string, unknown>>
  provenance: AnalyticsProvenance[]
  warnings: string[]
  insufficient: boolean
  message?: string | null
  source_documents?: string[]
  filters?: Record<string, unknown>
}

export interface EntityCompareResponse {
  metric: string
  period?: string | null
  chart_type: string
  data: Array<Record<string, unknown>>
  provenance: AnalyticsProvenance[]
  warnings: string[]
  insufficient: boolean
  message?: string | null
  source_documents?: string[]
  filters?: Record<string, unknown>
}

export interface TopicItem {
  id: string
  name: string
  slug?: string | null
  description?: string | null
  document_count: number
  chunk_count?: number
  keywords: string[]
  confidence?: number | null
  has_summary?: boolean
}

export interface TopicDetail extends TopicItem {
  summary?: string | null
  summary_citations?: Array<{
    document_id?: string
    document_name?: string
    page?: number | null
    snippet?: string
  }>
  evidence?: Array<{
    id: string
    document_id: string
    document_name?: string | null
    page?: number | null
    evidence_text: string
    confidence?: number | null
    matched_keywords?: string[]
  }>
  insufficient?: boolean
  llm_provider?: string
}
