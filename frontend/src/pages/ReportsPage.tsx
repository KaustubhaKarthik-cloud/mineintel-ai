import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  ApiError,
  deleteReport,
  downloadReportExcel,
  downloadReportFile,
  downloadReportPdf,
  formatDate,
  generateReport,
  getAnalyticsDimensions,
  getGeologyDocuments,
  getReports,
  type ReportItem,
} from '../lib/api'
import { PageHeader, StatusBadge } from '../components/ui'

type Domain = 'mining' | 'geological' | 'combined'

export function ReportsPage() {
  const { hasPermission } = useAuth()
  const canGenerate = hasPermission('reports.generate')
  const canDelete = hasPermission('reports.delete')
  const [reports, setReports] = useState<ReportItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [entities, setEntities] = useState<string[]>([])
  const [metrics, setMetrics] = useState<string[]>([])
  const [periods, setPeriods] = useState<string[]>([])
  const [documents, setDocuments] = useState<Array<{ id: string; name: string; kind: string }>>([])
  const [entity, setEntity] = useState('')
  const [metric, setMetric] = useState('production')
  const [period, setPeriod] = useState('')
  const [domain, setDomain] = useState<Domain>('mining')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [msg, setMsg] = useState('')

  const visibleDocs = useMemo(() => {
    if (domain === 'geological') return documents.filter((d) => d.kind === 'geological' || d.kind === 'both')
    if (domain === 'mining') return documents.filter((d) => d.kind === 'mining' || d.kind === 'both')
    return documents
  }, [documents, domain])

  async function reload() {
    setLoading(true)
    setError('')
    try {
      const res = await getReports()
      setReports(res.items)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Unable to load reports. Check the backend connection.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
    Promise.all([getAnalyticsDimensions(), getGeologyDocuments().catch(() => ({ items: [] }))]).then(
      ([d, geo]) => {
        setEntities(d.entities)
        setMetrics(d.metrics.length ? d.metrics : ['production'])
        setPeriods(d.periods)
        const miningDocs = (d.documents || []).map((x) => ({
          id: String(x.id),
          name: String(x.name || x.id),
          kind: 'mining',
        }))
        const geoDocs = (geo.items || []).map((x) => ({
          id: String(x.document_id),
          name: String(x.document_name || x.document_id),
          kind: 'geological',
        }))
        const byId = new Map<string, { id: string; name: string; kind: string }>()
        for (const item of [...miningDocs, ...geoDocs]) {
          const prev = byId.get(item.id)
          if (!prev) byId.set(item.id, item)
          else if (prev.kind !== item.kind) byId.set(item.id, { ...item, kind: 'both' })
        }
        setDocuments(Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name)))
        if (d.entities.includes('CIL')) setEntity('CIL')
        else if (d.entities[0]) setEntity(d.entities[0])
        if (d.metrics.includes('coal')) setMetric('coal')
        else if (d.metrics.includes('production')) setMetric('production')
        else if (d.metrics[0]) setMetric(d.metrics[0])
      },
    )
  }, [])

  async function onGenerate() {
    if (!canGenerate) return
    setGenerating(true)
    setMsg('')
    setError('')
    try {
      const r = await generateReport({
        entity: domain === 'geological' ? undefined : entity || undefined,
        metric: domain === 'geological' ? undefined : metric,
        period: domain === 'geological' ? undefined : period || undefined,
        document_ids: selectedDocs.length ? selectedDocs : undefined,
        report_type: domain,
        domain,
      })
      setMsg(`Created: ${r.title}`)
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Report generation failed')
    } finally {
      setGenerating(false)
    }
  }

  async function onDelete(id: string) {
    if (!confirm('Delete this report?')) return
    try {
      await deleteReport(id)
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Delete failed')
    }
  }

  function toggleDoc(id: string) {
    setSelectedDocs((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return (
    <div>
      <PageHeader
        title="Reports"
        subtitle="Generate mining, geological, or combined intelligence reports from verified/compatible structured evidence. Export HTML, PDF, or Excel."
      />

      <section className="panel mb-6 rounded-lg p-5">
        <h2 className="font-display text-lg uppercase tracking-wide text-ore-100">Generate report</h2>
        {!canGenerate ? (
          <p className="mt-2 text-sm text-signal-amber">
            Your role can view reports but cannot generate them.
          </p>
        ) : null}

        <div className="mt-3 flex flex-wrap gap-2">
          {(
            [
              ['mining', 'Mining'],
              ['geological', 'Geological'],
              ['combined', 'Combined'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => {
                setDomain(id)
                setSelectedDocs([])
              }}
              className={[
                'rounded-md px-3 py-1.5 text-sm font-medium',
                domain === id
                  ? 'bg-copper-500/20 text-copper-300 ring-1 ring-copper-500/40'
                  : 'bg-ore-850 text-ore-300 hover:text-ore-100',
              ].join(' ')}
            >
              {label}
            </button>
          ))}
        </div>

        {domain !== 'geological' ? (
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <label className="text-xs text-ore-400">
              Entity
              <select
                className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm"
                value={entity}
                onChange={(e) => setEntity(e.target.value)}
              >
                <option value="">Any / first available</option>
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
                className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm"
                value={metric}
                onChange={(e) => setMetric(e.target.value)}
              >
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
                className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              >
                <option value="">All</option>
                {periods.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        {visibleDocs.length ? (
          <div className="mt-3">
            <p className="text-xs text-ore-500">Source documents (optional)</p>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {visibleDocs.map((d) => (
                <li key={d.id}>
                  <label className="flex items-center gap-2 text-sm text-ore-200">
                    <input
                      type="checkbox"
                      checked={selectedDocs.includes(d.id)}
                      onChange={() => toggleDoc(d.id)}
                    />
                    {d.name}
                    <span className="text-[10px] uppercase text-ore-500">{d.kind}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-3 text-xs text-ore-500">
            No documents available for this domain yet. Report will still generate with empty/warning sections.
          </p>
        )}

        <button
          type="button"
          disabled={generating || !canGenerate}
          onClick={onGenerate}
          className="mt-4 rounded bg-copper-600 px-4 py-2 text-sm font-semibold text-ore-950 disabled:opacity-40"
        >
          {generating ? 'Generating…' : 'Generate report'}
        </button>
        {msg ? <p className="mt-2 text-sm text-signal-green">{msg}</p> : null}
      </section>

      {error ? <p className="mb-4 text-sm text-signal-red">{error}</p> : null}
      {loading ? <p className="text-ore-400">Loading reports…</p> : null}
      {!loading && reports.length === 0 ? (
        <p className="text-sm text-ore-500">No reports yet. Generate one from verified data above.</p>
      ) : null}

      <div className="space-y-3 animate-fade-up">
        {reports.map((r) => (
          <div key={r.id} className="panel flex flex-wrap items-center justify-between gap-3 rounded-lg px-5 py-4">
            <div className="min-w-0 flex-1">
              <Link to={`/reports/${r.id}`} className="font-medium text-ore-100 hover:text-copper-300">
                {r.title}
              </Link>
              <p className="mt-0.5 text-xs text-ore-500">
                {r.domain || r.report_type} · {formatDate(r.created_at)}
                {r.generated_by ? ` · by ${r.generated_by}` : ''}
              </p>
              {r.source_documents?.length ? (
                <p className="mt-1 text-xs text-ore-400">Sources: {r.source_documents.join(', ')}</p>
              ) : null}
              <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
                {r.pending_verification ? (
                  <span className="text-signal-amber">Pending human verification</span>
                ) : null}
                {r.open_conflicts ? (
                  <span className="text-signal-amber">{r.open_conflicts} open conflict(s)</span>
                ) : null}
                {r.insufficient ? (
                  <span className="text-ore-500">Insufficient evidence for some sections</span>
                ) : null}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={r.status} />
              <button
                type="button"
                className="rounded bg-ore-800 px-2 py-1 text-xs text-ore-200 hover:bg-ore-700"
                onClick={() => downloadReportFile(r.id, r.title).catch(() => undefined)}
              >
                HTML
              </button>
              <button
                type="button"
                className="rounded bg-ore-800 px-2 py-1 text-xs text-ore-200 hover:bg-ore-700"
                onClick={() => downloadReportPdf(r.id, r.title).catch(() => undefined)}
              >
                PDF
              </button>
              <button
                type="button"
                className="rounded bg-ore-800 px-2 py-1 text-xs text-ore-200 hover:bg-ore-700"
                onClick={() => downloadReportExcel(r.id, r.title).catch(() => undefined)}
              >
                Excel
              </button>
              {canDelete ? (
                <button
                  type="button"
                  className="rounded bg-signal-red/20 px-2 py-1 text-xs text-signal-red"
                  onClick={() => onDelete(r.id)}
                >
                  Delete
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
