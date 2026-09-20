import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ApiError,
  documentFileUrl,
  getActualVsTarget,
  getAnalytics,
  getAnalyticsDimensions,
  getAnalyticsTrend,
  getEntityCompare,
} from '../lib/api'
import type {
  ActualVsTargetResponse,
  AnalyticsData,
  AnalyticsProvenance,
  AnalyticsTrendResponse,
  EntityCompareResponse,
} from '../types'
import { PageHeader } from '../components/ui'

function ProvenanceList({ items }: { items: AnalyticsProvenance[] }) {
  if (!items?.length) return <p className="text-xs text-ore-500">No provenance attached.</p>
  return (
    <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-ore-300">
      {items.map((p, i) => (
        <li key={`${p.fact_id || i}-${p.value}`} className="rounded bg-ore-900/40 px-2 py-1 ring-1 ring-ore-800">
          <span className="text-copper-300">{p.value}</span>
          {p.unit ? ` ${p.unit}` : ''} · {p.entity || '—'} / {p.metric || '—'} / {p.period || '—'}
          <br />
          {p.document_id ? (
            <Link
              to={`/documents/${p.document_id}${p.page != null ? `#page-${p.page}` : ''}`}
              className="text-copper-400 hover:text-copper-300"
            >
              {p.document_name || p.document_id}
              {p.page != null ? ` · p.${p.page}` : ''}
            </Link>
          ) : (
            <span className="text-ore-500">{p.document_name}</span>
          )}
          {p.document_id ? (
            <>
              {' · '}
              <a
                href={documentFileUrl(p.document_id, p.page)}
                target="_blank"
                rel="noreferrer"
                className="text-ore-400 hover:text-ore-200"
              >
                file
              </a>
            </>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

export function AnalyticsPage() {
  const [overview, setOverview] = useState<AnalyticsData | null>(null)
  const [overviewError, setOverviewError] = useState('')
  const [documents, setDocuments] = useState<
    Array<{ id: string; name: string; structured_fact_count?: number }>
  >([])
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [entities, setEntities] = useState<string[]>([])
  const [metrics, setMetrics] = useState<string[]>([])
  const [periods, setPeriods] = useState<string[]>([])
  const [months, setMonths] = useState<string[]>([])
  const [entity, setEntity] = useState('')
  const [metric, setMetric] = useState('')
  const [period, setPeriod] = useState('')
  const [reportingMonth, setReportingMonth] = useState('')
  const [compareEntity, setCompareEntity] = useState('')
  const [trend, setTrend] = useState<AnalyticsTrendResponse | null>(null)
  const [avt, setAvt] = useState<ActualVsTargetResponse | null>(null)
  const [compare, setCompare] = useState<EntityCompareResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [dimsLoading, setDimsLoading] = useState(true)

  useEffect(() => {
    getAnalytics()
      .then(setOverview)
      .catch((e) => setOverviewError(e instanceof Error ? e.message : 'Failed to load overview'))
  }, [])

  useEffect(() => {
    setDimsLoading(true)
    getAnalyticsDimensions(selectedDocs.length ? selectedDocs : undefined)
      .then((d) => {
        setDocuments(d.documents || [])
        setEntities(d.entities)
        setMetrics(d.metrics)
        setPeriods(d.periods)
        setMonths(d.reporting_months || [])
        if (!entity && d.entities[0]) setEntity(d.entities[0])
        if (!metric) {
          if (d.metrics.includes('production')) setMetric('production')
          else if (d.metrics.includes('coal')) setMetric('coal')
          else if (d.metrics[0]) setMetric(d.metrics[0])
        }
        if (!period && d.periods[0]) setPeriod('')
        if (!compareEntity && d.entities[1]) setCompareEntity(d.entities[1])
      })
      .finally(() => setDimsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDocs.join(',')])

  function toggleDoc(id: string) {
    setSelectedDocs((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const canQuery = Boolean(entity && metric)

  async function runAnalytics() {
    if (!canQuery) return
    setLoading(true)
    setError(null)
    try {
      const docIds = selectedDocs.length ? selectedDocs : undefined
      const [t, a] = await Promise.all([
        getAnalyticsTrend({
          entity,
          metric,
          documentIds: docIds,
          reporting_month: reportingMonth || undefined,
        }),
        getActualVsTarget({
          entity,
          period: period || undefined,
          documentIds: docIds,
          reporting_month: reportingMonth || undefined,
        }),
      ])
      setTrend(t)
      setAvt(a)
      if (compareEntity && compareEntity !== entity) {
        setCompare(
          await getEntityCompare({
            entities: [entity, compareEntity],
            metric,
            period: period || undefined,
            documentIds: docIds,
            reporting_month: reportingMonth || undefined,
          }),
        )
      } else {
        setCompare(null)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Analytics request failed')
    } finally {
      setLoading(false)
    }
  }

  const trendData = useMemo(
    () =>
      (trend?.data || []).map((row) => ({
        year: String(row.year || row.period || ''),
        value: Number(row.value),
      })),
    [trend],
  )

  const filterSummary = [
    entity && `Entity: ${entity}`,
    metric && `Metric: ${metric}`,
    period && `FY: ${period}`,
    reportingMonth && `Month: ${reportingMonth}`,
    selectedDocs.length ? `${selectedDocs.length} document(s)` : 'All documents',
  ]
    .filter(Boolean)
    .join(' · ')

  if (overviewError && !overview) {
    return <p className="text-signal-red">Unable to load analytics. Check the backend connection.</p>
  }
  if (!overview && !overviewError) return <p className="text-ore-400">Loading analytics…</p>

  return (
    <div>
      <PageHeader
        title="Analytics"
        subtitle="Charts and KPIs from verified structured facts only — every point keeps document/page provenance."
      />

      {overview ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {overview.kpis.map((k, i) => (
            <div key={k.label} className="panel rounded-lg p-5 animate-fade-up" style={{ animationDelay: `${i * 50}ms` }}>
              <p className="text-xs uppercase tracking-[0.14em] text-ore-400">{k.label}</p>
              <p className="mt-2 font-display text-3xl text-ore-100">
                {typeof k.value === 'number' && k.value < 1 && k.value > 0
                  ? `${Math.round(k.value * 100)}%`
                  : k.value}
                {k.unit ? <span className="ml-1 text-lg text-ore-400">{k.unit}</span> : null}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      <section className="panel mt-6 rounded-lg p-5">
        <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Documents</h2>
        <p className="mt-1 text-xs text-ore-500">
          Select one or more PDFs from the database. Charts use only their verified structured data.
        </p>
        {dimsLoading ? (
          <p className="mt-3 text-sm text-ore-400">Loading documents…</p>
        ) : documents.length === 0 ? (
          <p className="mt-3 text-sm text-ore-500">No documents available yet.</p>
        ) : (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {documents.map((d) => (
              <li key={d.id}>
                <label className="flex cursor-pointer items-start gap-2 rounded border border-ore-800 bg-ore-900/40 px-3 py-2 text-sm hover:border-copper-500/40">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selectedDocs.includes(d.id)}
                    onChange={() => toggleDoc(d.id)}
                  />
                  <span>
                    <span className="text-ore-100">{d.name}</span>
                    <span className="mt-0.5 block text-[11px] text-ore-500">
                      {d.structured_fact_count ?? 0} structured facts
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel mt-6 rounded-lg p-5">
        <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Filters</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3 lg:grid-cols-5">
          <label className="text-xs text-ore-400">
            Entity
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={entity}
              onChange={(e) => setEntity(e.target.value)}
            >
              <option value="">Select…</option>
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
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            >
              <option value="">All years</option>
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
              <option value="">All months</option>
              {months.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ore-400">
            Compare with
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={compareEntity}
              onChange={(e) => setCompareEntity(e.target.value)}
            >
              <option value="">None</option>
              {entities.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          type="button"
          disabled={!canQuery || loading}
          onClick={runAnalytics}
          className="mt-4 rounded bg-copper-600 px-4 py-2 text-sm font-medium text-ore-950 disabled:opacity-40"
        >
          {loading ? 'Loading…' : 'Load charts'}
        </button>
        {error ? <p className="mt-2 text-sm text-signal-red">{error}</p> : null}
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section className="panel rounded-lg p-5">
          <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Production Trends</h2>
          <p className="text-xs text-ore-500">
            {trend?.unit ? `Units: ${trend.unit}` : 'Units: —'} · {filterSummary}
          </p>
          {trend?.source_documents?.length ? (
            <p className="mt-1 text-xs text-ore-500">Sources: {trend.source_documents.join(', ')}</p>
          ) : null}
          {trend?.warnings?.map((w) => (
            <p key={w} className="text-xs text-signal-amber">
              {w}
            </p>
          ))}
          {trend?.insufficient ? (
            <p className="mt-3 text-sm text-ore-400">
              {trend.message || 'Insufficient verified structured data for this analysis.'}
            </p>
          ) : trend ? (
            <div className="mt-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#314038" />
                  <XAxis dataKey="year" tick={{ fill: '#8a9e92', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#8a9e92', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1c2420', border: '1px solid #4a5c52', borderRadius: 8 }}
                  />
                  <Line type="monotone" dataKey="value" stroke="#c8843a" strokeWidth={2} dot />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-3 text-sm text-ore-500">Load charts to see production trends.</p>
          )}
          <p className="mt-2 text-xs uppercase tracking-wide text-ore-500">Source / Provenance</p>
          <ProvenanceList items={trend?.provenance || []} />
        </section>

        <section className="panel rounded-lg p-5">
          <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Actual vs Target</h2>
          <p className="text-xs text-ore-500">{filterSummary}</p>
          {avt?.insufficient ? (
            <p className="mt-3 text-sm text-ore-400">
              {avt.message || 'Insufficient verified structured data for this analysis.'}
            </p>
          ) : avt ? (
            <>
              <p className="mt-2 text-sm text-ore-300">
                Actual <span className="text-copper-300">{avt.actual}</span>
                {avt.unit ? ` ${avt.unit}` : ''} · Target{' '}
                <span className="text-copper-300">{avt.target}</span>
                {avt.achievement_percentage != null ? (
                  <>
                    {' '}
                    · Achievement <span className="text-signal-green">{avt.achievement_percentage}%</span>
                  </>
                ) : null}
              </p>
              <div className="mt-3 h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={avt.data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#314038" />
                    <XAxis dataKey="label" tick={{ fill: '#8a9e92', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#8a9e92', fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ background: '#1c2420', border: '1px solid #4a5c52', borderRadius: 8 }}
                    />
                    <Bar dataKey="value" fill="#4a7c8c" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <p className="mt-3 text-sm text-ore-500">Load charts to see actual vs target.</p>
          )}
          <p className="mt-2 text-xs uppercase tracking-wide text-ore-500">Source / Provenance</p>
          <ProvenanceList items={avt?.provenance || []} />
        </section>

        <section className="panel rounded-lg p-5 lg:col-span-2">
          <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Entity Comparison</h2>
          <p className="text-xs text-ore-500">{filterSummary}</p>
          {compare?.warnings?.map((w) => (
            <p key={w} className="text-xs text-signal-amber">
              {w}
            </p>
          ))}
          {compare?.insufficient ? (
            <p className="mt-3 text-sm text-ore-400">
              {compare.message || 'Insufficient verified structured data for this analysis.'}
            </p>
          ) : compare && !compare.insufficient ? (
            <div className="mt-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={compare.data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#314038" />
                  <XAxis dataKey="entity" tick={{ fill: '#8a9e92', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#8a9e92', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1c2420', border: '1px solid #4a5c52', borderRadius: 8 }}
                  />
                  <Legend />
                  <Bar dataKey="value" name={compare.metric} fill="#c8843a" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-3 text-sm text-ore-500">Select a second entity and load charts to compare.</p>
          )}
          <p className="mt-2 text-xs uppercase tracking-wide text-ore-500">Source / Provenance</p>
          <ProvenanceList items={compare?.provenance || []} />
        </section>
      </div>
    </div>
  )
}
