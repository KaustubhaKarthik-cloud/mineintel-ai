import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
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
import { chatAssistant, documentFileUrl, getSystemStatus } from '../lib/api'
import type { AssistantChart, ChatMessage } from '../types'
import { PageHeader } from '../components/ui'

const SUGGESTIONS = [
  "What was Mine B's production in FY2024?",
  'Compare Mine B production from FY2022 to FY2025',
  "What does the annual report say about Mine B?",
  'Show Mine B production from FY2022 to FY2025 and explain the trend',
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
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'MineIntel AI Assistant. I answer only from verified structured facts and retrieved document evidence. I never invent numbers. If values conflict, I show both sides.',
    },
  ])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [aiBanner, setAiBanner] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

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

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    setInput('')
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: 'user', content: trimmed }])
    setLoading(true)
    try {
      const res = await chatAssistant(trimmed, sessionId)
      setSessionId(res.session_id)
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: res.reply,
          sources: res.sources,
          query_type: res.query_type ?? undefined,
          structured_evidence: res.structured_evidence,
          rag_evidence: res.rag_evidence,
          conflicts: res.conflicts,
          chart: res.chart ?? null,
          warnings: res.warnings,
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

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <PageHeader
        title="AI Assistant"
        subtitle="Evidence-grounded Q&A over verified structured mining facts + document RAG. Conflicts are never auto-resolved."
      />

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
                  </p>
                ) : null}
                <p className="whitespace-pre-wrap">{msg.content}</p>

                {msg.conflicts && msg.conflicts.length > 0 ? (
                  <div className="mt-3 rounded-md bg-signal-amber/10 p-3 ring-1 ring-signal-amber/30">
                    <p className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-signal-amber">
                      <AlertTriangle className="h-3.5 w-3.5" /> Conflict detected
                    </p>
                    {(msg.conflicts as Array<Record<string, unknown>>).map((c) => (
                      <div key={String(c.id)} className="mt-2 text-xs text-ore-200">
                        <p className="font-medium text-ore-100">
                          {String(c.entity_name ?? '')} · {String(c.field_name ?? '')} ·{' '}
                          {String(c.period ?? '')}
                        </p>
                        {Array.isArray(c.evidence)
                          ? (c.evidence as Array<Record<string, unknown>>).map((e, i) => (
                              <p key={i} className="mt-1 text-ore-400">
                                {String(e.label ?? '')}: {String(e.document ?? '')} page{' '}
                                {String(e.page ?? '—')} → {String(e.value ?? '')}{' '}
                                {String(e.unit ?? '')}
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
                      Verified structured data
                    </p>
                    {msg.structured_evidence.slice(0, 6).map((e, i) => (
                      <p key={i} className="text-xs text-ore-400">
                        {String(e.entity)} · {String(e.metric)} · {String(e.period)} ={' '}
                        {String(e.value)} {String(e.unit ?? '')} · {String(e.source)} p
                        {String(e.page ?? '—')}
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
