import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Sparkles } from 'lucide-react'
import { ApiError, displayFileType, documentFileUrl, extractDocument, getDocument, indexDocument } from '../lib/api'
import type { DocumentDetail, ExtractedFact } from '../types'
import { ConfidenceBar, PageHeader, StatusBadge } from '../components/ui'

export function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [extractMsg, setExtractMsg] = useState('')
  const [indexMsg, setIndexMsg] = useState('')
  const [highlightPage, setHighlightPage] = useState<number | null>(null)

  function reload() {
    if (!id) return
    return getDocument(id)
      .then(setDoc)
      .catch((e: Error) => setError(e.message))
  }

  useEffect(() => {
    if (!id) return
    try {
      localStorage.setItem('mineintel.current_document_id', id)
    } catch {
      /* ignore */
    }
    reload()
  }, [id])

  async function runExtract() {
    if (!id) return
    setExtracting(true)
    setExtractMsg('Running AI extraction…')
    setError('')
    try {
      const summary = await extractDocument(id)
      setExtractMsg(
        `Done — ${summary.job.facts_count} facts, ${summary.job.review_count} need review (${summary.job.provider}).`,
      )
      await reload()
    } catch (e) {
      setExtractMsg('')
      setError(e instanceof ApiError ? e.message : 'Extraction failed')
    } finally {
      setExtracting(false)
    }
  }

  async function runIndex() {
    if (!id) return
    setIndexing(true)
    setIndexMsg('Indexing vectors…')
    setError('')
    try {
      const res = await indexDocument(id)
      setIndexMsg(`Indexed — ${res.chunk_count} chunks (${res.index_status}).`)
      await reload()
    } catch (e) {
      setIndexMsg('')
      setError(e instanceof ApiError ? e.message : 'Indexing failed')
    } finally {
      setIndexing(false)
    }
  }

  if (error && !doc) {
    return (
      <div>
        <p className="text-signal-red">{error}</p>
        <Link to="/documents" className="mt-4 inline-block text-sm text-copper-400">
          ← Back to documents
        </Link>
      </div>
    )
  }

  if (!doc) {
    return <p className="text-ore-400">Loading extracted content…</p>
  }

  const facts: ExtractedFact[] = doc.facts ?? []

  return (
    <div>
      <Link
        to="/documents"
        className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ore-400 hover:text-copper-300"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Documents
      </Link>

      <PageHeader
        title={doc.original_filename}
        subtitle="Page/sheet text (Phase 2) and AI facts with evidence (Phase 3)."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={doc.status} />
            <a
              href={documentFileUrl(doc.id)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-md bg-ore-800 px-4 py-2 text-sm font-semibold text-ore-100 ring-1 ring-ore-600 hover:bg-ore-700"
            >
              Open original file
            </a>
            <Link
              to={`/assistant?document_id=${encodeURIComponent(doc.id)}`}
              className="inline-flex items-center gap-2 rounded-md bg-ore-800 px-4 py-2 text-sm font-semibold text-ore-100 ring-1 ring-ore-600 hover:bg-ore-700"
            >
              Ask about this report
            </Link>
            <button
              type="button"
              disabled={extracting || doc.status === 'failed' || doc.status === 'processing'}
              onClick={runExtract}
              className="inline-flex items-center gap-2 rounded-md bg-copper-500 px-4 py-2 text-sm font-semibold text-ore-950 hover:bg-copper-400 disabled:opacity-40"
            >
              <Sparkles className="h-4 w-4" />
              {extracting ? 'Extracting…' : 'Run AI extraction'}
            </button>
            <button
              type="button"
              disabled={indexing || doc.status === 'failed' || doc.status === 'processing'}
              onClick={runIndex}
              className="inline-flex items-center gap-2 rounded-md bg-ore-800 px-4 py-2 text-sm font-semibold text-ore-100 ring-1 ring-ore-600 hover:bg-ore-700 disabled:opacity-40"
            >
              {indexing
                ? 'Indexing…'
                : doc.index_status === 'indexed'
                  ? 'Re-index document'
                  : 'Index document'}
            </button>
          </div>
        }
      />

      {extractMsg ? <p className="mb-2 text-sm text-signal-green">{extractMsg}</p> : null}
      {indexMsg ? <p className="mb-2 text-sm text-signal-green">{indexMsg}</p> : null}
      {error ? <p className="mb-4 text-sm text-signal-red">{error}</p> : null}

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 animate-fade-up">
        {[
          { label: 'Type', value: displayFileType(doc) },
          { label: 'Processing', value: doc.status },
          { label: 'AI extraction', value: doc.extraction_completed ? 'completed' : 'pending' },
          { label: 'Vector index', value: doc.index_status ?? 'not_indexed' },
        ].map((row) => (
          <div key={row.label} className="panel rounded-lg px-4 py-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-ore-500">{row.label}</p>
            <p className="mt-1 text-sm capitalize text-ore-100">{String(row.value).replace(/_/g, ' ')}</p>
          </div>
        ))}
      </div>

      <section className="mb-8 animate-fade-up">
        <h2 className="mb-4 font-display text-2xl uppercase tracking-wide text-ore-100">AI extraction</h2>
        {facts.length === 0 ? (
          <div className="panel rounded-lg p-5 text-sm text-ore-400">
            No structured mining (ExtractedFact) rows yet. Geological exploration reports may still have
            G1 geological facts — open{' '}
            <Link to="/geology" className="text-copper-400 hover:text-copper-300">
              Geological Explorer
            </Link>{' '}
            or{' '}
            <Link to="/analytics" className="text-copper-400 hover:text-copper-300">
              Analytics
            </Link>{' '}
            (select this document). Zero mining facts does not mean zero geological structured data.
            For production reports: ensure Phase 2 finished, then click{' '}
            <strong className="text-ore-200">Run AI extraction</strong>.
          </div>
        ) : (
          <div className="panel overflow-x-auto rounded-lg">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-ore-700/50 text-xs uppercase tracking-[0.12em] text-ore-500">
                  <th className="px-4 py-3 font-medium">Field</th>
                  <th className="px-4 py-3 font-medium">Value</th>
                  <th className="px-4 py-3 font-medium">Confidence</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {facts.map((f) => (
                  <tr key={f.id} className="border-b border-ore-800/70 hover:bg-ore-850/40">
                    <td className="px-4 py-3">
                      <p className="font-mono text-xs text-copper-300">{f.field_name}</p>
                      {f.entity_name ? <p className="text-xs text-ore-500">{f.entity_name}</p> : null}
                      {f.is_calculated ? (
                        <p className="text-[10px] uppercase text-signal-blue">Calculated</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-ore-100">
                      {f.value}
                      {f.unit ? ` ${f.unit}` : ''}
                      {f.financial_year ? (
                        <span className="ml-2 text-xs text-ore-500">{f.financial_year}</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <ConfidenceBar value={f.confidence_score} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={f.status} />
                      {f.has_conflict ? (
                        <p className="mt-1 text-[10px] uppercase tracking-wide text-signal-amber">
                          Conflicting report detected
                          {f.conflict_ids?.[0] ? (
                            <>
                              {' · '}
                              <Link to="/validation" className="text-copper-400 hover:text-copper-300">
                                View conflict
                              </Link>
                            </>
                          ) : null}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        className="text-xs font-semibold text-copper-400 hover:text-copper-300"
                        onClick={() => setHighlightPage(f.page_number ?? null)}
                      >
                        {f.sheet_name
                          ? `Sheet: ${f.sheet_name}`
                          : f.page_number != null
                            ? `Page ${f.page_number}`
                            : 'Source'}
                      </button>
                      {f.evidence_text ? (
                        <p className="mt-1 max-w-xs text-xs text-ore-500 line-clamp-2">{f.evidence_text}</p>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {doc.latest_extraction_job?.warnings?.length ? (
          <ul className="mt-3 space-y-1 text-xs text-signal-amber">
            {doc.latest_extraction_job.warnings.map((w) => (
              <li key={w}>⚠ {w}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="animate-fade-up" style={{ animationDelay: '80ms' }}>
        <h2 className="mb-4 font-display text-2xl uppercase tracking-wide text-ore-100">
          Extracted content
        </h2>
        <div className="space-y-4">
          {doc.pages.map((page) => (
            <article
              key={page.id}
              id={`page-${page.page_number}`}
              className={[
                'panel rounded-lg p-5 transition',
                highlightPage === page.page_number ? 'ring-2 ring-copper-500/60' : '',
              ].join(' ')}
            >
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-ore-700/40 pb-3">
                <div>
                  {page.source_type === 'excel_sheet' ? (
                    <h3 className="font-display text-lg uppercase tracking-wide text-copper-300">
                      Sheet: {page.sheet_name ?? 'Untitled'}
                    </h3>
                  ) : (
                    <h3 className="font-display text-lg uppercase tracking-wide text-copper-300">
                      Page {page.page_number}
                    </h3>
                  )}
                </div>
                <span className="text-xs tabular-nums text-ore-500">{page.char_count} chars</span>
              </div>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ore-200">
                {page.text || '(no text on this page)'}
              </pre>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
