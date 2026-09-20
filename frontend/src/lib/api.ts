import type {
  AnalyticsData,
  ChatSource,
  DashboardStats,
  DocumentDetail,
  DocumentItem,
  ReviewItem,
} from '../types'

const API_BASE = '/api'
const TOKEN_KEY = 'mineintel_token'

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const headers: Record<string, string> = {
    ...(extra as Record<string, string> | undefined),
  }
  const token = getAuthToken()
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: authHeaders(init?.headers),
    })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function fetchJsonOrThrow<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: authHeaders(init?.headers),
  })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export type AuthUserInfo = {
  id: string
  username: string
  display_name?: string | null
  role: string
  status?: string
  permissions?: string[]
  anonymous?: boolean
  auth_required?: boolean
}

export async function login(username: string, password: string) {
  const data = await fetchJsonOrThrow<{ access_token: string; user: AuthUserInfo }>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  setAuthToken(data.access_token)
  return data
}

export async function logout() {
  try {
    await fetchJsonOrThrow<{ status: string }>('/auth/logout', { method: 'POST' })
  } catch {
    /* ignore */
  }
  setAuthToken(null)
}

export async function getMe() {
  return fetchJsonOrThrow<AuthUserInfo>('/auth/me')
}

export async function listUsers() {
  return fetchJsonOrThrow<{
    total: number
    items: Array<{
      id: string
      username: string
      display_name?: string | null
      role: string
      status: string
      created_at?: string | null
      last_login_at?: string | null
    }>
  }>('/users')
}

export async function createUser(body: {
  username: string
  password: string
  display_name?: string
  role: string
}) {
  return fetchJsonOrThrow('/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function updateUser(
  id: string,
  body: { display_name?: string; role?: string; status?: string; password?: string },
) {
  return fetchJsonOrThrow(`/users/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function getDashboard(): Promise<DashboardStats> {
  const data = await fetchJson<DashboardStats>('/dashboard')
  if (data) return data
  throw new ApiError(0, 'Unable to reach dashboard API. Is the backend running?')
}

/** Live documents from backend — empty list is valid (no mock fallback on success). */
export async function getDocuments(): Promise<DocumentItem[]> {
  const data = await fetchJson<{ items: DocumentItem[] }>('/documents')
  if (data) return data.items
  throw new ApiError(0, 'Unable to reach document API. Is the backend running?')
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  return fetchJsonOrThrow<DocumentDetail>(`/documents/${id}`)
}

export function documentFileUrl(id: string, page?: number | null) {
  const base = `${API_BASE}/documents/${id}/file`
  return page != null ? `${base}#page=${page}` : base
}

export async function getDocumentStatus(id: string) {
  return fetchJsonOrThrow<{
    id: string
    status: string
    processing_stage?: string | null
    error_message?: string | null
    page_count: number
    is_scanned: boolean
    ocr_completed: boolean
  }>(`/documents/${id}/status`)
}

export async function getReviews(): Promise<{ items: ReviewItem[]; pending: number }> {
  const data = await fetchJson<{ items: ReviewItem[]; pending: number }>('/reviews')
  if (!data) {
    throw new ApiError(0, 'Unable to reach review API. Is the backend running?')
  }
  return data
}

export async function submitReviewAction(
  id: string,
  action: 'approve' | 'reject' | 'correct',
  corrected_value?: string,
  extra?: {
    corrected_unit?: string
    entity_name?: string
    financial_year?: string
    review_notes?: string
  },
): Promise<ReviewItem | null> {
  return fetchJson<ReviewItem>(`/reviews/${id}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action,
      corrected_value,
      corrected_unit: extra?.corrected_unit,
      entity_name: extra?.entity_name,
      financial_year: extra?.financial_year,
      review_notes: extra?.review_notes,
      reviewer: 'demo_user',
    }),
  })
}

export async function getAnalytics(): Promise<AnalyticsData> {
  const data = await fetchJson<AnalyticsData>('/analytics')
  if (data) return data
  throw new ApiError(0, 'Unable to reach analytics API. Is the backend running?')
}

export type AnalyticsDimensions = {
  entities: string[]
  metrics: string[]
  periods: string[]
  reporting_months?: string[]
  measurement_types?: string[]
  documents?: Array<{
    id: string
    name: string
    file_type?: string
    status?: string
    page_count?: number
    structured_fact_count?: number
    has_structured_data?: boolean
  }>
}

export async function getAnalyticsDimensions(documentIds?: string[]) {
  const q = new URLSearchParams()
  for (const id of documentIds || []) q.append('document_id', id)
  const suffix = q.toString() ? `?${q}` : ''
  return (
    (await fetchJson<AnalyticsDimensions>(`/analytics/dimensions${suffix}`)) ?? {
      entities: [],
      metrics: [],
      periods: [],
      reporting_months: [],
      measurement_types: [],
      documents: [],
    }
  )
}

export async function getAnalyticsTrend(params: {
  entity?: string
  metric: string
  period?: string[]
  documentIds?: string[]
  reporting_month?: string
  measurement_type?: string
}) {
  const q = new URLSearchParams()
  q.set('metric', params.metric)
  if (params.entity) q.set('entity', params.entity)
  for (const p of params.period || []) q.append('period', p)
  for (const id of params.documentIds || []) q.append('document_id', id)
  if (params.reporting_month) q.set('reporting_month', params.reporting_month)
  if (params.measurement_type) q.set('measurement_type', params.measurement_type)
  return fetchJsonOrThrow<import('../types').AnalyticsTrendResponse>(`/analytics/trend?${q}`)
}

export async function getActualVsTarget(params: {
  entity: string
  period?: string
  actual_metric?: string
  target_metric?: string
  documentIds?: string[]
  reporting_month?: string
}) {
  const q = new URLSearchParams()
  q.set('entity', params.entity)
  if (params.period) q.set('period', params.period)
  if (params.actual_metric) q.set('actual_metric', params.actual_metric)
  if (params.target_metric) q.set('target_metric', params.target_metric)
  for (const id of params.documentIds || []) q.append('document_id', id)
  if (params.reporting_month) q.set('reporting_month', params.reporting_month)
  return fetchJsonOrThrow<import('../types').ActualVsTargetResponse>(
    `/analytics/actual-vs-target?${q}`,
  )
}

export async function getEntityCompare(params: {
  entities: string[]
  metric: string
  period?: string
  documentIds?: string[]
  reporting_month?: string
  measurement_type?: string
}) {
  const q = new URLSearchParams()
  q.set('metric', params.metric)
  for (const e of params.entities) q.append('entities', e)
  if (params.period) q.set('period', params.period)
  for (const id of params.documentIds || []) q.append('document_id', id)
  if (params.reporting_month) q.set('reporting_month', params.reporting_month)
  if (params.measurement_type) q.set('measurement_type', params.measurement_type)
  return fetchJsonOrThrow<import('../types').EntityCompareResponse>(`/analytics/compare?${q}`)
}

export async function chatAssistant(
  message: string,
  sessionId?: string,
): Promise<{
  session_id: string
  reply: string
  sources: ChatSource[]
  query_type?: string | null
  structured_evidence?: Array<Record<string, unknown>>
  rag_evidence?: Array<Record<string, unknown>>
  conflicts?: Array<Record<string, unknown>>
  chart?: import('../types').AssistantChart | null
  warnings?: string[]
}> {
  const data = await fetchJson<{
    session_id: string
    reply: string
    sources: ChatSource[]
    query_type?: string | null
    structured_evidence?: Array<Record<string, unknown>>
    rag_evidence?: Array<Record<string, unknown>>
    conflicts?: Array<Record<string, unknown>>
    chart?: import('../types').AssistantChart | null
    warnings?: string[]
  }>('/assistant/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (data) return data

  return {
    session_id: sessionId ?? 'local',
    reply:
      'Assistant backend unreachable. Start the API on port 8000, then ask again.',
    sources: [],
    warnings: ['Backend offline'],
  }
}

export async function uploadDocument(
  file: File,
  mineName: string,
  category: string,
): Promise<DocumentDetail> {
  const form = new FormData()
  form.append('file', file)
  form.append('mine_name', mineName)
  form.append('document_category', category)
  return fetchJsonOrThrow<DocumentDetail>('/documents/upload', { method: 'POST', body: form })
}

export async function extractDocument(documentId: string) {
  return fetchJsonOrThrow<{
    job: import('../types').ExtractionJob
    facts: import('../types').ExtractedFact[]
  }>(`/documents/${documentId}/extract`, { method: 'POST' })
}

export async function indexDocument(documentId: string) {
  return fetchJsonOrThrow<{
    document_id: string
    index_status: string
    embedding_completed: boolean
    indexed_at?: string | null
    chunk_count: number
    index_error?: string | null
  }>(`/documents/${documentId}/index`, { method: 'POST' })
}

export async function semanticSearch(query: string, topK = 8) {
  return fetchJsonOrThrow<{
    query: string
    results: Array<{
      text: string
      score: number
      document?: string | null
      document_id: string
      page?: number | null
      sheet_name?: string | null
      source_location?: string | null
      content_type: string
      document_version: number
      chunk_id: string
      has_conflict?: boolean
      conflict_ids?: string[]
    }>
    context?: string | null
  }>('/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK, include_context: true }),
  })
}

export async function getExploreDimensions() {
  return fetchJsonOrThrow<{
    entities: string[]
    metrics: string[]
    periods: string[]
    reporting_months: string[]
    measurement_types: string[]
    documents: Array<Record<string, unknown>>
  }>('/explore/dimensions')
}

export async function getExploreDocuments() {
  return fetchJsonOrThrow<{ total: number; items: Array<Record<string, unknown>> }>(
    '/explore/documents',
  )
}

export async function getExploreStructuredFacts(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v) q.set(k, v)
  })
  return fetchJsonOrThrow<{ total: number; items: Array<Record<string, unknown>> }>(
    `/explore/structured-facts?${q}`,
  )
}

export async function getExploreChunks(params: Record<string, string | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v) q.set(k, v)
  })
  return fetchJsonOrThrow<{ total: number; items: Array<Record<string, unknown>> }>(
    `/explore/chunks?${q}`,
  )
}

export async function runValidation() {
  return fetchJsonOrThrow<{
    facts_scanned: number
    conflicts_detected: number
    created: number
    refreshed: number
    auto_cleared: number
  }>('/validation/run', { method: 'POST' })
}

export async function getValidationStats() {
  return fetchJsonOrThrow<import('../types').ValidationStats>('/validation/stats')
}

export async function getValidationConflicts(status?: string) {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return fetchJsonOrThrow<{ total: number; items: import('../types').ValidationConflict[] }>(
    `/validation/conflicts${q}`,
  )
}

export async function getValidationConflict(id: string) {
  return fetchJsonOrThrow<import('../types').ValidationConflict>(`/validation/conflicts/${id}`)
}

export async function confirmValidationConflict(id: string, notes?: string) {
  return fetchJsonOrThrow<import('../types').ValidationConflict>(`/validation/conflicts/${id}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notes }),
  })
}

export async function dismissValidationConflict(id: string, reason?: string) {
  return fetchJsonOrThrow<import('../types').ValidationConflict>(`/validation/conflicts/${id}/dismiss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
}

export async function resolveValidationConflict(
  id: string,
  selected_value: string,
  selected_unit?: string,
  reason?: string,
) {
  return fetchJsonOrThrow<import('../types').ValidationConflict>(`/validation/conflicts/${id}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ selected_value, selected_unit, reason }),
  })
}

export async function getDocumentFacts(documentId: string) {
  return fetchJsonOrThrow<import('../types').ExtractedFact[]>(`/documents/${documentId}/facts`)
}

export async function getTopics(refresh = false) {
  const q = refresh ? '?refresh=true' : ''
  const data = await fetchJson<{ items: import('../types').TopicItem[] }>(`/topics${q}`)
  if (data?.items) return data.items
  throw new ApiError(0, 'Unable to reach topics API. Is the backend running?')
}

export async function getTopicDetail(id: string) {
  return fetchJsonOrThrow<import('../types').TopicDetail>(`/topics/${id}`)
}

export async function summarizeTopic(id: string) {
  return fetchJsonOrThrow<import('../types').TopicDetail>(`/topics/${id}/summary`, {
    method: 'POST',
  })
}

export async function extractTopics(documentId?: string) {
  const q = documentId ? `?document_id=${encodeURIComponent(documentId)}` : ''
  return fetchJsonOrThrow<{ topics: number; evidence_added: number; chunks_scanned: number }>(
    `/topics/extract${q}`,
    { method: 'POST' },
  )
}

export type ReportItem = {
  id: string
  title: string
  report_type: string
  status: string
  generated_by?: string | null
  created_at?: string | null
  source_documents?: string[]
  parameters?: Record<string, unknown>
  has_content?: boolean
  content?: string
}

export async function getReports() {
  return fetchJsonOrThrow<{ total: number; items: ReportItem[] }>('/reports')
}

export async function generateReport(body: {
  title?: string
  report_type?: string
  entity?: string
  metric?: string
  period?: string
  document_ids?: string[]
}) {
  return fetchJsonOrThrow<ReportItem>('/reports/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function getReport(id: string) {
  return fetchJsonOrThrow<ReportItem>(`/reports/${id}`)
}

export function reportViewUrl(id: string) {
  return `${API_BASE}/reports/${id}/view`
}

export function reportDownloadUrl(id: string) {
  return `${API_BASE}/reports/${id}/download`
}

export async function downloadReportFile(id: string, title?: string) {
  const res = await fetch(`${API_BASE}/reports/${id}/download`, {
    headers: authHeaders(),
  })
  if (!res.ok) {
    let detail = `Download failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(title || 'report').replace(/\s+/g, '_').slice(0, 80)}.html`
  a.click()
  URL.revokeObjectURL(url)
}

export async function deleteReport(id: string) {
  return fetchJsonOrThrow<{ status: string; id: string }>(`/reports/${id}`, { method: 'DELETE' })
}

export async function getSystemStatus() {
  return fetchJsonOrThrow<Record<string, unknown>>('/system/status')
}

export async function getAuditLogs() {
  return fetchJsonOrThrow<{
    total: number
    items: Array<{
      id: string
      action: string
      entity_type?: string | null
      entity_id?: string | null
      actor?: string | null
      details?: Record<string, unknown> | null
      created_at?: string | null
    }>
  }>('/system/audit-logs')
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDate(iso?: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function displayFileType(doc: DocumentItem) {
  if (doc.file_type === 'pdf' && doc.is_scanned) return 'Scanned PDF'
  if (doc.file_type === 'pdf') return 'PDF'
  if (doc.file_type === 'excel') return 'Excel'
  if (doc.file_type === 'image') return 'Image'
  return doc.file_type.toUpperCase()
}

export function statusColor(status: string) {
  const map: Record<string, string> = {
    approved: 'text-signal-green',
    completed: 'text-signal-green',
    pending_review: 'text-signal-amber',
    review_required: 'text-signal-amber',
    pending: 'text-signal-amber',
    processing: 'text-signal-blue',
    extracted: 'text-copper-400',
    uploaded: 'text-ore-300',
    failed: 'text-signal-red',
    rejected: 'text-signal-red',
    corrected: 'text-signal-blue',
    ready: 'text-signal-green',
    draft: 'text-ore-400',
    demo: 'text-copper-400',
    operational: 'text-signal-green',
  }
  return map[status] ?? 'text-ore-300'
}

export function statusLabel(status: string) {
  return status.replace(/_/g, ' ')
}

export function stageLabel(stage?: string | null) {
  const map: Record<string, string> = {
    uploaded: 'Uploaded',
    extracting_text: 'Extracting text…',
    detecting_pdf_type: 'Detecting PDF type…',
    ocr: 'OCR required…',
    completed: 'Processing complete',
    failed: 'Processing failed',
  }
  return stage ? map[stage] ?? stage.replace(/_/g, ' ') : ''
}
