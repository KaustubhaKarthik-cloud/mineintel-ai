import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { documentFileUrl, extractTopics, getTopicDetail, getTopics, summarizeTopic } from '../lib/api'
import type { TopicDetail, TopicItem } from '../types'
import { PageHeader } from '../components/ui'

export function TopicsPage() {
  const [topics, setTopics] = useState<TopicItem[]>([])
  const [selected, setSelected] = useState<TopicDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh(forceExtract = false) {
    setLoading(true)
    setError(null)
    try {
      if (forceExtract) await extractTopics()
      const items = await getTopics(forceExtract)
      setTopics(items)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load topics')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh(false)
  }, [])

  async function openTopic(id: string) {
    setBusy(true)
    setError(null)
    try {
      setSelected(await getTopicDetail(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load topic')
    } finally {
      setBusy(false)
    }
  }

  async function runSummary() {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      setSelected(await summarizeTopic(selected.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Summary failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Topics"
        subtitle="Thematic clusters from document evidence — summaries are grounded in retrieved chunks with citations."
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => refresh(true)}
          className="rounded bg-copper-600 px-3 py-1.5 text-sm text-ore-950"
          disabled={busy || loading}
        >
          Re-extract topics
        </button>
        {selected ? (
          <button
            type="button"
            onClick={runSummary}
            className="rounded bg-ore-700 px-3 py-1.5 text-sm text-ore-100 ring-1 ring-ore-600"
            disabled={busy}
          >
            {busy ? 'Working…' : 'Generate grounded summary'}
          </button>
        ) : null}
      </div>
      {error ? <p className="mb-3 text-sm text-signal-red">{error}</p> : null}

      {loading ? (
        <p className="text-ore-400">Loading topics…</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:col-span-2 lg:grid-cols-1">
            {topics.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => openTopic(t.id)}
                className={`panel rounded-lg p-5 text-left transition ${
                  selected?.id === t.id ? 'ring-1 ring-copper-500' : ''
                }`}
              >
                <h3 className="font-display text-xl uppercase tracking-wide text-ore-100">{t.name}</h3>
                <p className="mt-1 text-sm text-ore-400">
                  {t.document_count} documents
                  {t.chunk_count != null ? ` · ${t.chunk_count} chunks` : ''}
                </p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(t.keywords || []).slice(0, 6).map((k) => (
                    <span
                      key={k}
                      className="rounded bg-ore-800 px-2 py-0.5 text-[11px] text-copper-300 ring-1 ring-ore-700"
                    >
                      {k}
                    </span>
                  ))}
                </div>
              </button>
            ))}
            {!topics.length ? (
              <p className="text-sm text-ore-400">No topics yet. Index documents, then re-extract.</p>
            ) : null}
          </div>

          <div className="panel rounded-lg p-5 lg:col-span-3">
            {!selected ? (
              <p className="text-ore-400">Select a topic to view evidence and summary.</p>
            ) : (
              <>
                <h2 className="font-display text-2xl uppercase tracking-wide text-ore-100">{selected.name}</h2>
                {selected.summary ? (
                  <div className="mt-4 whitespace-pre-wrap rounded bg-ore-900/50 p-4 text-sm text-ore-200 ring-1 ring-ore-800">
                    {selected.summary}
                    {selected.llm_provider ? (
                      <p className="mt-3 text-xs text-ore-500">Provider: {selected.llm_provider}</p>
                    ) : null}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-ore-500">No summary yet — generate one from retrieved evidence.</p>
                )}

                {selected.summary_citations?.length ? (
                  <div className="mt-4">
                    <h3 className="text-xs uppercase tracking-wide text-ore-500">Citations</h3>
                    <ul className="mt-2 space-y-2 text-xs text-ore-300">
                      {selected.summary_citations.map((c, i) => (
                        <li key={i} className="rounded bg-ore-900/40 px-2 py-1.5 ring-1 ring-ore-800">
                          {c.document_id ? (
                            <>
                              <Link
                                to={`/documents/${c.document_id}${c.page != null ? `#page-${c.page}` : ''}`}
                                className="font-medium text-copper-300 hover:text-copper-200"
                              >
                                {c.document_name || c.document_id}
                                {c.page != null ? ` · Page ${c.page}` : ''}
                              </Link>
                              {' · '}
                              <a
                                href={documentFileUrl(c.document_id, c.page)}
                                target="_blank"
                                rel="noreferrer"
                                className="text-ore-400 hover:text-ore-200"
                              >
                                File
                              </a>
                            </>
                          ) : (
                            <>
                              {c.document_name}
                              {c.page != null ? ` · Page ${c.page}` : ''}
                            </>
                          )}
                          <div className="mt-1 text-ore-500">{c.snippet}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="mt-5">
                  <h3 className="text-xs uppercase tracking-wide text-ore-500">Evidence chunks</h3>
                  <ul className="mt-2 max-h-[28rem] space-y-2 overflow-y-auto">
                    {(selected.evidence || []).map((e) => (
                      <li key={e.id} className="rounded bg-ore-900/40 p-3 text-sm text-ore-200 ring-1 ring-ore-800">
                        <p className="text-xs text-copper-300">
                          <Link
                            to={`/documents/${e.document_id}${e.page != null ? `#page-${e.page}` : ''}`}
                            className="hover:text-copper-200"
                          >
                            {e.document_name || e.document_id}
                            {e.page != null ? ` · Page ${e.page}` : ''}
                          </Link>
                          {e.confidence != null ? ` · conf ${e.confidence}` : ''}
                          {' · '}
                          <a
                            href={documentFileUrl(e.document_id, e.page)}
                            target="_blank"
                            rel="noreferrer"
                            className="text-ore-400 hover:text-ore-200"
                          >
                            File
                          </a>
                        </p>
                        <p className="mt-1 whitespace-pre-wrap text-ore-300">{e.evidence_text}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
