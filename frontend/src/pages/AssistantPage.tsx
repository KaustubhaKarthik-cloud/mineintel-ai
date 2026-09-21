import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, FileSearch, Send } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chatAssistant, documentFileUrl, getDocuments, getSystemStatus } from '../lib/api'
import type { AssistantChart, ChatMessage, DocumentItem } from '../types'
import { PageHeader } from '../components/ui'

const CURRENT_DOC_KEY = 'mineintel.current_document_id'

const SUGGESTIONS = [
  "What was Mine B's production in FY2024?",
  'Compare Mine B production from FY2022 to FY2025',
  "What does the annual report say about Mine B?",
  'Show Mine B production from FY2022 to FY2025 and explain the trend',
  'What coal seams are reported in this exploration report?',
]

function ChartBlock({ chart }: { chart: AssistantChart }) {
  const data = chart.data || []
  if (!data.length) return null
  const Chart = chart.type === 'bar' ? BarChart : LineChart
  return (
    <div className="mt-3 rounded-md bg-ore-950/40 p-3 ring-1 ring-ore-700/50">
      <p className="text-xs font-medium text-ore-200">{chart.title}</p>
      <p className="mt-0.5 text-[10px] uppercase tracking-wide text-ore-500">
        {chart.x_axis} · {chart.y_axis}
      </p>
      <div className="mt-2 h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <Chart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3a4540" />
            <XAxis dataKey="year" stroke="#8a948c" fontSize={11} />
            <YAxis stroke="#8a948c" fontSize={11} />
            <Tooltip
              contentStyle={{ background: '#1a221e', border: '1px solid #3a4540', borderRadius: 8 }}
            />
            {chart.type === 'bar' ? (
              <Bar dataKey="value" fill="#c8843a" radius={[4, 4, 0, 0]} />
            ) : (
              <Line type="monotone" dataKey="value" stroke="#c8843a" strokeWidth={2} dot />
            )}
          </Chart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[10px] text-ore-500">Values from verified structured facts only.</p>
    </div>
  )
}

export function AssistantPage() {
  const [searchParams] = useSearchParams()
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'MineIntel AI Assistant. I answer only from verified structured facts and retrieved document evidence. I never invent numbers. If values conflict, I show both sides. Select a current document for “this report” questions.',
    },
  ])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [aiBanner, setAiBanner] = useState('')
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [currentDocumentId, setCurrentDocumentId] = useState<string>(() => {
    try {
      return localStorage.getItem(CURRENT_DOC_KEY) || ''
    } catch {
      return ''
    }
  })
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    getDocuments()
      .then((items) => setDocuments(items || []))
      .catch(() => setDocuments([]))
  }, [])

  useEffect(() => {
    const fromUrl = searchParams.get('document_id') || searchParams.get('doc')
    if (fromUrl) {
      setCurrentDocumentId(fromUrl)
      try {
        localStorage.setItem(CURRENT_DOC_KEY, fromUrl)
      } catch {
        /* ignore */
      }
    }
  }, [searchParams])

  useEffect(() => {
    getSystemStatus()
      .then((s) => {
        const ai = (s.ai_assistant || {}) as Record<string, unknown>
        if (ai.message) setAiBanner(String(ai.message))
        else if (ai.connection_health === 'unavailable') {
          setAiBanner(
            'Local AI unavailable. Start Ollama and load the configured model to enable AI Assistant features.',
          )
        }
      })
      .catch(() => {
        /* ignore */
      })
  }, [])

  function selectDocument(id: string) {
    setCurrentDocumentId(id)
    // Document switch must not reuse prior session evidence/entity context
    setSessionId(undefined)
    try {
      if (id) localStorage.setItem(CURRENT_DOC_KEY, id)
      else localStorage.removeItem(CURRENT_DOC_KEY)
    } catch {
      /* ignore */
    }
  }

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    const deictic =
      /\b(this|the|current)\s+(report|document|pdf|exploration\s+report)\b/i.test(trimmed) ||
      /\bin\s+this\s+report\b/i.test(trimmed)
    if (deictic && !currentDocumentId) {
      setMessages((m) => [
        ...m,
        { id: `u-${Date.now()}`, role: 'user', content: trimmed },
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content:
            'Select a current document above before asking about “this report”. Without a selected document the assistant will not search other reports.',
          warnings: ['Current document required for this-report questions'],
        },
      ])
      setInput('')
      return
    }
    setInput('')
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: 'user', content: trimmed }])
    setLoading(true)
    try {
      const res = await chatAssistant(trimmed, sessionId, currentDocumentId || undefined)
      setSessionId(res.session_id)
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: res.reply,
          sources: res.sources,
          query_type: res.query_type ?? undefined,
          domain: res.domain ?? undefined,
          geological_intent: res.geological_intent ?? undefined,
          is_geological: Boolean(res.is_geological),
          structured_evidence: res.structured_evidence,
          rag_evidence: res.rag_evidence,
          conflicts: res.conflicts,
          chart: res.chart ?? null,
          warnings: res.warnings,
          llm: res.llm ?? undefined,
        },
      ])
    } catch {
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: 'Assistant request failed. Check that the API is running.',
          warnings: ['Request failed'],
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const currentDocLabel =
    documents.find((d) => d.id === currentDocumentId)?.original_filename ||
    documents.find((d) => d.id === currentDocumentId)?.filename ||
    ''

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <PageHeader
        title="AI Assistant"
        subtitle="Evidence-grounded Q&A over verified structured mining facts + document RAG. Conflicts are never auto-resolved."
      />

      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-ore-900/40 px-3 py-2 ring-1 ring-ore-700/40">
        <label className="text-[11px] uppercase tracking-wide text-ore-500" htmlFor="current-doc">
          Current document
        </label>
        <select
          id="current-doc"
          className="min-w-[14rem] flex-1 rounded border border-ore-700 bg-ore-950 px-2 py-1.5 text-sm text-ore-100"
          value={currentDocumentId}
          onChange={(e) => selectDocument(e.target.value)}
        >
          <option value="">(none — multi-document search)</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {d.original_filename || d.filename}
            </option>
          ))}
        </select>
        {currentDocLabel ? (
          <span className="text-xs text-ore-400">“This report” → {currentDocLabel}</span>
        ) : null}
      </div>

      {aiBanner ? (
        <p className="mb-3 rounded-md border border-signal-amber/40 bg-signal-amber/10 px-3 py-2 text-sm text-signal-amber">
          {aiBanner}
        </p>
      ) : null}

      <div className="panel flex min-h-0 flex-1 flex-col rounded-lg animate-fade-up">
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[92%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-copper-500/20 text-ore-100 ring-1 ring-copper-500/30'
                    : 'panel-inset text-ore-200'
                }`}
              >
                {msg.query_type ? (
                  <p className="mb-2 text-[10px] uppercase tracking-[0.14em] text-ore-500">
                    Route: {msg.query_type}
                    {msg.domain ? ` · Domain: ${msg.domain}` : ''}
                    {msg.geological_intent ? ` · Intent: ${msg.geological_intent}` : ''}
                  </p>
                ) : null}
                <p className="whitespace-pre-wrap">{msg.content}</p>

                {msg.conflicts && msg.conflicts.length > 0 ? (
                  <div className="mt-3 rounded-md bg-signal-amber/10 p-3 ring-1 ring-signal-amber/30">
                    <p className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-signal-amber">
                      <AlertTriangle className="h-3.5 w-3.5" />{' '}
                      {String(
                        (msg.conflicts as Array<Record<string, unknown>>)[0]?.conflict_type ===
                          'cross_document_discrepancy'
                          ? 'Cross-document discrepancy'
                          : 'Conflict detected',
                      )}
                    </p>
                    <p className="mt-1 text-[11px] text-ore-300">
                      Conflicting evidence requires human verification. Both sources are shown.
                    </p>
                    {(msg.conflicts as Array<Record<string, unknown>>).map((c) => (
                      <div key={String(c.id)} className="mt-2 text-xs text-ore-200">
                        <p className="font-medium text-ore-100">
                          {String(c.entity_name ?? '')} · {String(c.field_name ?? '')}
                          {c.period ? ` · ${String(c.period)}` : ''}
                          {c.conflict_type ? ` · ${String(c.conflict_type)}` : ''}
                          {c.status ? ` · ${String(c.status)}` : ''}
                        </p>
                        {Array.isArray(c.evidence)
                          ? (c.evidence as Array<Record<string, unknown>>).map((e, i) => (
                              <p key={i} className="mt-1 text-ore-400">
                                {String(e.label ?? '')}: {String(e.document ?? '')} page{' '}
                                {String(e.page ?? '—')} → {String(e.value ?? '')}{' '}
                                {String(e.unit ?? '')}
                                {e.status ? ` (${String(e.status)})` : ''}
                              </p>
                            ))
                          : null}
                        <Link
                          to="/validation"
                          className="mt-2 inline-block text-[10px] font-semibold uppercase tracking-wide text-copper-400"
                        >
                          Open validation
                        </Link>
                      </div>
                    ))}
                  </div>
                ) : null}

                {msg.chart ? <ChartBlock chart={msg.chart} /> : null}

                {msg.structured_evidence && msg.structured_evidence.length > 0 ? (
                  <div className="mt-3 space-y-1 border-t border-ore-700/40 pt-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-signal-green">
                      {msg.domain === 'geological' || msg.is_geological
                        ? 'Structured geological evidence'
                        : 'Verified structured data'}
                    </p>
                    {msg.structured_evidence.slice(0, 6).map((e, i) => (
                      <p key={i} className="text-xs text-ore-400">
                        {String(e.entity ?? '')}
                        {e.seam_name ? ` · ${String(e.seam_name)}` : ''}
                        {e.seam_status ? ` [${String(e.seam_status)}]` : ''}
                        {' · '}
                        {String(e.metric)}
                        {e.period ? ` · ${String(e.period)}` : ''} = {String(e.value)}{' '}
                        {String(e.unit ?? '')} · {String(e.source)} p{String(e.page ?? '—')}
                        {e.status ? ` · ${String(e.status)}` : ''}
                      </p>
                    ))}
                  </div>
                ) : null}

                {msg.rag_evidence && msg.rag_evidence.length > 0 ? (
                  <div className="mt-3 space-y-1 border-t border-ore-700/40 pt-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-signal-blue">
                      Document evidence
                    </p>
                    {msg.rag_evidence.slice(0, 3).map((e, i) => (
                      <p key={i} className="text-xs text-ore-400 line-clamp-3">
                        [{String(e.document)}, page {String(e.page ?? '—')}] {String(e.evidence)}
                      </p>
                    ))}
                  </div>
                ) : null}

                {msg.sources && msg.sources.length > 0 ? (
                  <div className="mt-3 space-y-2 border-t border-ore-700/40 pt-3">
                    <p className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-ore-500">
                      <FileSearch className="h-3 w-3" /> Citations
                    </p>
                    {msg.sources.map((s) => (
                      <div key={s.document_id + s.snippet.slice(0, 12)} className="rounded bg-ore-950/50 px-2.5 py-2">
                        <Link
                          to={`/documents/${s.document_id}${s.page != null ? `#page-${s.page}` : ''}`}
                          className="text-xs font-medium text-copper-300 hover:text-copper-200"
                        >
                          {s.document_name}
                          {s.page != null ? ` · Page ${s.page}` : ''}
                          <span className="text-ore-500"> ({Math.round(s.relevance * 100)}%)</span>
                        </Link>
                        {' · '}
                        <a
                          href={documentFileUrl(s.document_id, s.page)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-ore-400 hover:text-ore-200"
                        >
                          Open file
                        </a>
                        <p className="mt-0.5 text-xs text-ore-400 line-clamp-2">{s.snippet}</p>
                      </div>
                    ))}
                  </div>
                ) : null}

                {msg.warnings && msg.warnings.length > 0 ? (
                  <ul className="mt-2 space-y-1 text-[11px] text-signal-amber">
                    {msg.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          ))}
          {loading ? (
            <p className="text-sm text-ore-500 animate-pulse-soft">Retrieving evidence…</p>
          ) : null}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-ore-700/40 px-4 py-3">
          <div className="mb-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                className="rounded-md bg-ore-800/80 px-2.5 py-1 text-xs text-ore-300 ring-1 ring-ore-700 transition hover:text-copper-300"
              >
                {s}
              </button>
            ))}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about mines, production, reports…"
              className="panel-inset flex-1 rounded-md px-3 py-2.5 text-sm text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-copper-500 px-4 py-2.5 text-sm font-semibold text-ore-950 hover:bg-copper-400 disabled:opacity-40"
            >
              <Send className="h-4 w-4" /> Ask
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
