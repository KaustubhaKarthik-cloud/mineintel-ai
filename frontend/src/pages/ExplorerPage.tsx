import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  documentFileUrl,
  formatDate,
  getExploreChunks,
  getExploreDimensions,
  getExploreDocuments,
  getExploreStructuredFacts,
} from '../lib/api'
import { PageHeader } from '../components/ui'

type Tab = 'documents' | 'structured' | 'evidence'

export function ExplorerPage() {
  const [tab, setTab] = useState<Tab>('structured')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [entities, setEntities] = useState<string[]>([])
  const [metrics, setMetrics] = useState<string[]>([])
  const [periods, setPeriods] = useState<string[]>([])
  const [months, setMonths] = useState<string[]>([])
  const [measures, setMeasures] = useState<string[]>([])
  const [dimDocs, setDimDocs] = useState<Array<{ id: string; name: string }>>([])
  const [docs, setDocs] = useState<Array<Record<string, unknown>>>([])
  const [facts, setFacts] = useState<Array<Record<string, unknown>>>([])
  const [chunks, setChunks] = useState<Array<Record<string, unknown>>>([])
  const [factTotal, setFactTotal] = useState(0)
  const [chunkTotal, setChunkTotal] = useState(0)
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null)

  const [documentId, setDocumentId] = useState('')
  const [entity, setEntity] = useState('')
  const [metric, setMetric] = useState('')
  const [fiscalYear, setFiscalYear] = useState('')
  const [reportingMonth, setReportingMonth] = useState('')
  const [measurementType, setMeasurementType] = useState('')

  useEffect(() => {
    getExploreDimensions()
      .then((d) => {
        setEntities(d.entities || [])
        setMetrics(d.metrics || [])
        setPeriods(d.periods || [])
        setMonths(d.reporting_months || [])
        setMeasures(d.measurement_types || [])
        setDimDocs(
          (d.documents || []).map((x) => ({
            id: String(x.id),
            name: String(x.name || x.id),
          })),
        )
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Unable to load filters.'))
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        if (tab === 'documents') {
          const res = await getExploreDocuments()
          if (!cancelled) setDocs(res.items)
        } else if (tab === 'structured') {
          const res = await getExploreStructuredFacts({
            document_id: documentId || undefined,
            entity: entity || undefined,
            metric: metric || undefined,
            fiscal_year: fiscalYear || undefined,
            reporting_month: reportingMonth || undefined,
            measurement_type: measurementType || undefined,
            limit: '300',
          })
          if (!cancelled) {
            setFacts(res.items)
            setFactTotal(res.total)
          }
        } else {
          const res = await getExploreChunks({
            document_id: documentId || undefined,
            limit: '200',
          })
          if (!cancelled) {
            setChunks(res.items)
            setChunkTotal(res.total)
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof ApiError
              ? e.message
              : 'Unable to load exploration data. Check the backend connection.',
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [tab, documentId, entity, metric, fiscalYear, reportingMonth, measurementType])

  return (
    <div>
      <PageHeader
        title="Data Exploration"
        subtitle="Browse documents, verified structured facts, and indexed evidence from the live database."
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {(
          [
            ['structured', 'Structured data'],
            ['documents', 'Documents'],
            ['evidence', 'Extracted evidence'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              setSelected(null)
              setTab(id)
            }}
            className={[
              'rounded-md px-4 py-2 text-sm font-medium',
              tab === id
                ? 'bg-copper-500/20 text-copper-300 ring-1 ring-copper-500/40'
                : 'bg-ore-850 text-ore-300 hover:text-ore-100',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {tab !== 'documents' ? (
        <div className="panel mb-4 rounded-lg p-4">
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            <label className="text-xs text-ore-400">
              Document
              <select
                className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                value={documentId}
                onChange={(e) => setDocumentId(e.target.value)}
              >
                <option value="">All</option>
                {dimDocs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            {tab === 'structured' ? (
              <>
                <label className="text-xs text-ore-400">
                  Entity
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={entity}
                    onChange={(e) => setEntity(e.target.value)}
                  >
                    <option value="">All</option>
                    {entities.map((e) => (
                      <option key={e} value={e}>
                        {e}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-ore-400">
                  Metric
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={metric}
                    onChange={(e) => setMetric(e.target.value)}
                  >
                    <option value="">All</option>
                    {metrics.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-ore-400">
                  Fiscal year
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={fiscalYear}
                    onChange={(e) => setFiscalYear(e.target.value)}
                  >
                    <option value="">All</option>
                    {periods.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-ore-400">
                  Reporting month
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={reportingMonth}
                    onChange={(e) => setReportingMonth(e.target.value)}
                  >
                    <option value="">All</option>
                    {months.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-ore-400">
                  Measure
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={measurementType}
                    onChange={(e) => setMeasurementType(e.target.value)}
                  >
                    <option value="">All</option>
                    {measures.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {error ? <p className="mb-4 text-sm text-signal-red">{error}</p> : null}
      {loading ? <p className="text-ore-400">Loading…</p> : null}

      {!loading && tab === 'documents' ? (
        docs.length === 0 ? (
          <p className="text-sm text-ore-500">No documents available yet.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {docs.map((d) => (
              <div key={String(d.id)} className="panel rounded-lg p-5">
                <p className="font-medium text-ore-100">{String(d.name)}</p>
                <p className="mt-1 text-xs text-ore-500">
                  {String(d.document_type || d.file_type || '')} · {String(d.status || '')} ·{' '}
                  {formatDate(d.upload_date as string)}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div className="panel-inset rounded px-2 py-1.5">
                    <dt className="text-[10px] uppercase text-ore-500">Pages</dt>
                    <dd>{String(d.page_count ?? '—')}</dd>
                  </div>
                  <div className="panel-inset rounded px-2 py-1.5">
                    <dt className="text-[10px] uppercase text-ore-500">Structured facts</dt>
                    <dd>{String(d.structured_fact_count ?? 0)}</dd>
                  </div>
                </dl>
                <div className="mt-3 flex gap-3 text-xs font-semibold uppercase tracking-wide">
                  <Link to={`/documents/${d.id}`} className="text-copper-400 hover:text-copper-300">
                    Details
                  </Link>
                  <a
                    href={documentFileUrl(String(d.id))}
                    target="_blank"
                    rel="noreferrer"
                    className="text-ore-300 hover:text-ore-100"
                  >
                    Open file
                  </a>
                </div>
              </div>
            ))}
          </div>
        )
      ) : null}

      {!loading && tab === 'structured' ? (
        <div className="grid gap-4 lg:grid-cols-5">
          <div className="panel overflow-x-auto rounded-lg lg:col-span-3">
            <p className="border-b border-ore-800 px-4 py-2 text-xs text-ore-500">
              {factTotal} structured fact{factTotal === 1 ? '' : 's'}
            </p>
            {facts.length === 0 ? (
              <p className="p-4 text-sm text-ore-500">
                No structured facts match these filters. Index PDF tables first.
              </p>
            ) : (
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr className="border-b border-ore-700/50 text-xs uppercase tracking-wide text-ore-500">
                    <th className="px-3 py-2">Entity</th>
                    <th className="px-3 py-2">Metric</th>
                    <th className="px-3 py-2">Month</th>
                    <th className="px-3 py-2">FY</th>
                    <th className="px-3 py-2">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {facts.map((f) => (
                    <tr
                      key={String(f.id)}
                      className="cursor-pointer border-b border-ore-800/60 hover:bg-ore-850/50"
                      onClick={() => setSelected(f)}
                    >
                      <td className="px-3 py-2 text-ore-100">{String(f.entity)}</td>
                      <td className="px-3 py-2 text-ore-300">{String(f.metric)}</td>
                      <td className="px-3 py-2 text-ore-400">{String(f.reporting_month || '—')}</td>
                      <td className="px-3 py-2 text-ore-400">{String(f.fiscal_year || '—')}</td>
                      <td className="px-3 py-2 text-copper-300">
                        {String(f.value)}
                        {f.unit ? ` ${f.unit}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="panel rounded-lg p-4 lg:col-span-2">
            <h3 className="font-display text-lg uppercase tracking-wide text-ore-100">Provenance</h3>
            {!selected ? (
              <p className="mt-3 text-sm text-ore-500">Select a row to inspect source evidence.</p>
            ) : (
              <div className="mt-3 space-y-2 text-sm text-ore-200">
                <p>
                  <span className="text-ore-500">Entity · Metric</span>
                  <br />
                  {String(selected.entity)} · {String(selected.metric)}
                </p>
                <p>
                  <span className="text-ore-500">Value</span>
                  <br />
                  <span className="text-copper-300">
                    {String(selected.value)}
                    {selected.unit ? ` ${selected.unit}` : ''}
                  </span>
                  {selected.reporting_month ? ` · ${String(selected.reporting_month)}` : ''}
                  {selected.fiscal_year ? ` · ${String(selected.fiscal_year)}` : ''}
                  {selected.measurement_type ? ` · ${String(selected.measurement_type)}` : ''}
                </p>
                <p>
                  <span className="text-ore-500">Source</span>
                  <br />
                  {String(selected.document_name)}
                  {selected.page != null ? ` — Page ${String(selected.page)}` : ''}
                  {selected.table_title ? ` — ${String(selected.table_title)}` : ''}
                </p>
                {selected.evidence_text ? (
                  <p className="rounded bg-ore-900/50 p-2 text-xs text-ore-400">
                    {String(selected.evidence_text)}
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-3 pt-2 text-xs font-semibold uppercase tracking-wide">
                  <Link
                    to={`/documents/${selected.document_id}${selected.page != null ? `#page-${selected.page}` : ''}`}
                    className="text-copper-400 hover:text-copper-300"
                  >
                    Open document
                  </Link>
                  <a
                    href={documentFileUrl(String(selected.document_id), selected.page as number)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-ore-300 hover:text-ore-100"
                  >
                    View original
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {!loading && tab === 'evidence' ? (
        chunks.length === 0 ? (
          <p className="text-sm text-ore-500">No evidence chunks available yet. Index documents first.</p>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-ore-500">
              {chunkTotal} evidence chunk{chunkTotal === 1 ? '' : 's'}
            </p>
            {chunks.map((c) => (
              <article key={String(c.id)} className="panel rounded-lg p-4">
                <div className="flex flex-wrap justify-between gap-2">
                  <p className="text-sm font-medium text-ore-100">{String(c.document_name)}</p>
                  <p className="text-xs text-ore-500">
                    {c.page != null
                      ? `Page ${String(c.page)}`
                      : c.sheet_name
                        ? `Sheet ${String(c.sheet_name)}`
                        : ''}
                    {' · '}
                    {String(c.content_type || '').replace(/_/g, ' ')}
                  </p>
                </div>
                <p className="mt-2 text-sm text-ore-300 line-clamp-4">{String(c.evidence_text)}</p>
                <Link
                  to={`/documents/${c.document_id}`}
                  className="mt-2 inline-block text-xs font-semibold uppercase tracking-wide text-copper-400"
                >
                  Open source
                </Link>
              </article>
            ))}
          </div>
        )
      ) : null}
    </div>
  )
}
