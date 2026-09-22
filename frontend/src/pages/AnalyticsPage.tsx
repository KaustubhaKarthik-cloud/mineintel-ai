import { useCallback, useEffect, useMemo, useState } from 'react'
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
  getAnalytics,
  getAnalyticsData,
  getAnalyticsDimensions,
  getEntityCompare,
} from '../lib/api'
import type {
  AnalyticsData,
  AnalyticsProvenance,
  AnalyticsTrendResponse,
  ActualVsTargetResponse,
  EntityCompareResponse,
} from '../types'
import { PageHeader } from '../components/ui'

type ChartKind = 'line' | 'bar'

type TableRow = {
  period: string
  actual?: number | string | null
  target?: number | null
  unit?: string | null
  source?: string | null
  page?: number | null
  document_id?: string | null
  evidence_available?: boolean
  evidence_note?: string
  achievement_percentage?: number | null
  status?: string | null
  seam?: string | null
  formation?: string | null
}

function ProvenanceList({ items }: { items: AnalyticsProvenance[] }) {
  if (!items?.length) {
    return <p className="text-xs text-ore-500">Evidence unavailable for these values.</p>
  }
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
            <span className="text-ore-500">{p.document_name || 'Evidence unavailable'}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function SelectField({
  label,
  value,
  onChange,
  options,
  labels,
  placeholder,
  disabled,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: string[]
  labels?: Record<string, string>
  placeholder?: string
  disabled?: boolean
}) {
  return (
    <label className="text-xs text-ore-400">
      {label}
      <select
        className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100 disabled:opacity-50"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{placeholder || 'Select…'}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {labels?.[o] || o}
          </option>
        ))}
      </select>
    </label>
  )
}

export function AnalyticsPage() {
  const [overview, setOverview] = useState<AnalyticsData | null>(null)
  const [overviewError, setOverviewError] = useState('')
  const [documents, setDocuments] = useState<
    Array<{
      id: string
      name: string
      structured_fact_count?: number
      geological_fact_count?: number
      production_fact_count?: number
      domain?: string | null
    }>
  >([])
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [domain, setDomain] = useState<'production' | 'geological' | 'mixed'>('production')

  const [entities, setEntities] = useState<string[]>([])
  const [commodities, setCommodities] = useState<string[]>([])
  const [commodityLabels, setCommodityLabels] = useState<Record<string, string>>({})
  const [metrics, setMetrics] = useState<string[]>([])
  const [metricLabels, setMetricLabels] = useState<Record<string, string>>({})
  const [measures, setMeasures] = useState<string[]>([])
  const [measureLabels, setMeasureLabels] = useState<Record<string, string>>({})
  const [periods, setPeriods] = useState<string[]>([])
  const [months, setMonths] = useState<string[]>([])
  const [seams, setSeams] = useState<string[]>([])
  const [formations, setFormations] = useState<string[]>([])
  const [seam, setSeam] = useState('')
  const [formation, setFormation] = useState('')

  const [entity, setEntity] = useState('')
  const [commodity, setCommodity] = useState('')
  const [metric, setMetric] = useState('')
  const [measure, setMeasure] = useState('')
  const [period, setPeriod] = useState('')
  const [reportingMonth, setReportingMonth] = useState('')
  const [compare, setCompare] = useState('target')
  const [compareEntity, setCompareEntity] = useState('')
  const [chartKind, setChartKind] = useState<ChartKind>('line')

  const [trend, setTrend] = useState<AnalyticsTrendResponse | null>(null)
  const [avt, setAvt] = useState<ActualVsTargetResponse | null>(null)
  const [compareResult, setCompareResult] = useState<EntityCompareResponse | null>(null)
  const [table, setTable] = useState<TableRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [dimsLoading, setDimsLoading] = useState(true)
  const [chartsTouched, setChartsTouched] = useState(false)

  useEffect(() => {
    getAnalytics()
      .then(setOverview)
      .catch((e) => setOverviewError(e instanceof Error ? e.message : 'Unable to load analytics.'))
  }, [])

  const loadRootDimensions = useCallback(async () => {
    setDimsLoading(true)
    try {
      const d = await getAnalyticsDimensions(selectedDocs.length ? selectedDocs : undefined)
      const resolved =
        d.domain === 'geological' ? 'geological' : d.domain === 'mixed' ? 'mixed' : 'production'
      setDomain(resolved)
      setDocuments(d.documents || [])
      setEntities(d.entities || [])
      setCommodities(d.commodities || [])
      setCommodityLabels(d.commodity_labels || {})
      setMetricLabels(d.metric_labels || {})
      setSeams(d.seams || [])
      setFormations(d.formations || [])
      const semantic = d.semantic_metrics?.length
        ? d.semantic_metrics
        : (d.metrics || []).filter((m) => !['coal', 'lignite', 'coking_coal'].includes(m))
      setMetrics(semantic.length ? semantic : d.metrics || [])
      setMeasures(d.measurement_types || [])
      setMeasureLabels(d.measure_labels || {})
      setPeriods(d.periods || [])
      setMonths(d.reporting_months || [])

      if (!entity && d.suggested_entity && d.entities.includes(d.suggested_entity)) {
        setEntity(d.suggested_entity)
      }
      if (resolved !== 'geological') {
        if (!commodity && d.suggested_commodity) {
          setCommodity(d.suggested_commodity)
        }
        if (!reportingMonth && d.suggested_reporting_month) {
          setReportingMonth(d.suggested_reporting_month)
        }
        if (!measure && (d.measurement_types || []).includes('during')) {
          setMeasure('during')
        }
      } else {
        setCommodity('')
        setMeasure('')
        setPeriod('')
        setReportingMonth('')
        setCompare('')
      }
      if (!metric) {
        if (d.suggested_metric && (semantic.includes(d.suggested_metric) || d.metrics.includes(d.suggested_metric))) {
          setMetric(
            resolved === 'geological'
              ? d.suggested_metric
              : d.suggested_metric === 'coal' || d.suggested_metric === 'lignite'
                ? 'production'
                : d.suggested_metric,
          )
        } else if (resolved !== 'geological' && semantic.includes('production')) setMetric('production')
        else if (semantic[0]) setMetric(semantic[0])
      }
      if (!compareEntity && d.entities.length > 1) {
        const other = d.entities.find((e) => e !== (d.suggested_entity || entity))
        if (other) setCompareEntity(other)
      }
    } catch {
      setError('Unable to load analytics.')
    } finally {
      setDimsLoading(false)
    }
  }, [selectedDocs, entity, commodity, metric, reportingMonth, compareEntity, measure])

  useEffect(() => {
    void loadRootDimensions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDocs.join(',')])

  // Dependent filters: when entity/commodity/metric change, refresh dependent lists
  useEffect(() => {
    if (domain === 'geological') return // geo dims already include seams/formations; no nested refetch
    if (!entity && !commodity && !metric) return
    getAnalyticsDimensions(selectedDocs.length ? selectedDocs : undefined, {
      entity: entity || undefined,
      commodity: commodity || undefined,
      metric: metric || undefined,
    })
      .then((d) => {
        if (entity) {
          setCommodities(d.commodities || [])
          setCommodityLabels(d.commodity_labels || {})
          if (commodity && !(d.commodities || []).includes(commodity)) setCommodity('')
        }
        const semantic = d.semantic_metrics?.length
          ? d.semantic_metrics
          : (d.metrics || []).filter((m) => !['coal', 'lignite', 'coking_coal'].includes(m))
        if (entity || commodity) {
          setMetrics(semantic.length ? semantic : d.metrics || [])
          if (metric && semantic.length && !semantic.includes(metric) && !['coal', 'lignite'].includes(metric)) {
            setMetric(semantic.includes('production') ? 'production' : semantic[0] || '')
          }
        }
        setMeasures(d.measurement_types || [])
        setMeasureLabels(d.measure_labels || {})
        setPeriods(d.periods || [])
        setMonths(d.reporting_months || [])
        if (period && d.periods?.length && !d.periods.includes(period)) setPeriod('')
      })
      .catch(() => {
        /* keep prior lists */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity, commodity, metric, selectedDocs.join(','), domain])

  function toggleDoc(id: string) {
    setSelectedDocs((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const isGeological = domain === 'geological'
  const canQuery = isGeological
    ? Boolean(selectedDocs.length > 0 || metric || entity)
    : Boolean(entity && (metric || commodity))

  async function runAnalytics() {
    if (!canQuery) return
    setLoading(true)
    setError(null)
    setChartsTouched(true)
    try {
      const docIds = selectedDocs.length ? selectedDocs : undefined
      const data = await getAnalyticsData({
        entity: entity || undefined,
        commodity: isGeological ? undefined : commodity || undefined,
        metric: metric || (isGeological ? undefined : 'production'),
        measure: isGeological ? undefined : measure || undefined,
        period: isGeological ? undefined : period || undefined,
        documentIds: docIds,
        reporting_month: isGeological ? undefined : reportingMonth || undefined,
        compare: isGeological ? undefined : compare || undefined,
        domain: isGeological ? 'geological' : undefined,
        seam: isGeological ? seam || undefined : undefined,
        formation: isGeological ? formation || undefined : undefined,
      })
      setTrend(data.trend)
      setAvt(isGeological ? null : data.actual_vs_target || null)
      setTable(data.table || [])
      if (data.insufficient) {
        setError(data.message || 'No analytics data available for this selection.')
      }

      if (!isGeological && compareEntity && compareEntity !== entity && metric) {
        setCompareResult(
          await getEntityCompare({
            entities: [entity, compareEntity],
            metric: commodity && metric === 'production' ? commodity : metric,
            commodity: commodity || undefined,
            period: period || undefined,
            documentIds: docIds,
            reporting_month: reportingMonth || undefined,
            measurement_type: measure || undefined,
          }),
        )
      } else {
        setCompareResult(null)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Unable to load analytics.')
      setTrend(null)
      setAvt(null)
      setTable([])
      setCompareResult(null)
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
    isGeological && 'Domain: Geological',
    entity && `Entity: ${entity}`,
    !isGeological && commodity && `Commodity: ${commodityLabels[commodity] || commodity}`,
    metric && `Metric: ${metricLabels[metric] || metric}`,
    isGeological && seam && `Seam: ${seam}`,
    isGeological && formation && `Formation: ${formation}`,
    !isGeological && measure && `Measure: ${measureLabels[measure] || measure}`,
    !isGeological && period && `FY: ${period}`,
    !isGeological && reportingMonth && `Month: ${reportingMonth}`,
    selectedDocs.length ? `${selectedDocs.length} document(s)` : 'All documents',
  ]
    .filter(Boolean)
    .join(' · ')

  if (overviewError && !overview) {
    return <p className="text-signal-red">Unable to load analytics.</p>
  }
  if (!overview && !overviewError) return <p className="text-ore-400">Loading analytics...</p>

  const Chart = chartKind === 'bar' ? BarChart : LineChart

  return (
    <div>
      <PageHeader
        title="Analytics"
        subtitle={
          isGeological
            ? 'Geological metrics from structured GeologicalFact rows only — never invented from RAG text.'
            : 'Entity · Commodity · Metric · Measure · Period — values from verified structured facts only, with source evidence.'
        }
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
          Optional: limit charts to selected PDFs. Values still come from structured facts, not vector search.
        </p>
        {dimsLoading ? (
          <p className="mt-3 text-sm text-ore-400">Loading documents…</p>
        ) : documents.length === 0 ? (
          <p className="mt-3 text-sm text-ore-500">No documents with structured analytics data yet.</p>
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
                      {d.domain === 'geological'
                        ? `${d.geological_fact_count ?? d.structured_fact_count ?? 0} geological facts`
                        : d.domain === 'mixed'
                          ? `${d.production_fact_count ?? 0} production · ${d.geological_fact_count ?? 0} geological`
                          : `${d.structured_fact_count ?? 0} structured facts`}
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
        <div className="mt-4 grid gap-3 md:grid-cols-3 lg:grid-cols-4">
          <SelectField
            label={isGeological ? 'Entity / Block' : 'Entity / Mine'}
            value={entity}
            onChange={(v) => {
              setEntity(v)
              setChartsTouched(false)
            }}
            options={entities}
            placeholder="Select entity…"
          />
          {!isGeological ? (
            <SelectField
              label="Commodity"
              value={commodity}
              onChange={(v) => {
                setCommodity(v)
                setChartsTouched(false)
              }}
              options={commodities}
              labels={commodityLabels}
              placeholder={commodities.length ? 'Select commodity…' : 'No commodity in data'}
              disabled={!commodities.length}
            />
          ) : null}
          <SelectField
            label="Metric"
            value={metric}
            onChange={(v) => {
              setMetric(v)
              setChartsTouched(false)
            }}
            options={metrics}
            labels={metricLabels}
            placeholder="Select metric…"
          />
          {isGeological ? (
            <>
              <SelectField
                label="Seam"
                value={seam}
                onChange={(v) => {
                  setSeam(v)
                  setChartsTouched(false)
                }}
                options={seams}
                placeholder="All seams"
              />
              <SelectField
                label="Formation"
                value={formation}
                onChange={(v) => {
                  setFormation(v)
                  setChartsTouched(false)
                }}
                options={formations}
                placeholder="All formations"
              />
            </>
          ) : (
            <>
              <SelectField
                label="Measure / Type"
                value={measure}
                onChange={setMeasure}
                options={measures}
                labels={measureLabels}
                placeholder={measures.length ? 'All measures' : '—'}
              />
              <SelectField
                label="Financial Year"
                value={period}
                onChange={setPeriod}
                options={periods}
                placeholder="All years"
              />
              <SelectField
                label="Reporting month"
                value={reportingMonth}
                onChange={setReportingMonth}
                options={months}
                placeholder="All months"
              />
              <SelectField
                label="Comparison"
                value={compare}
                onChange={setCompare}
                options={['target', 'during']}
                labels={{ target: 'Target', during: 'Actual only' }}
                placeholder="None"
              />
              <SelectField
                label="Compare entity"
                value={compareEntity}
                onChange={setCompareEntity}
                options={entities.filter((e) => e !== entity)}
                placeholder="None"
              />
            </>
          )}
          <SelectField
            label="Chart"
            value={chartKind}
            onChange={(v) => setChartKind(v as ChartKind)}
            options={['line', 'bar']}
            labels={{ line: 'Line Chart', bar: 'Bar Chart' }}
          />
        </div>
        <button
          type="button"
          disabled={!canQuery || loading}
          onClick={runAnalytics}
          className="mt-4 rounded bg-copper-600 px-4 py-2 text-sm font-medium text-ore-950 disabled:opacity-40"
        >
          {loading ? 'Loading analytics...' : 'Generate Analysis'}
        </button>
        {!canQuery && !dimsLoading ? (
          <p className="mt-3 text-sm text-ore-400">
            Select an Entity and a Metric (and Commodity when available) to generate analysis.
          </p>
        ) : null}
        {error ? <p className="mt-2 text-sm text-signal-red">{error}</p> : null}
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section className="panel rounded-lg p-5">
          <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Trend</h2>
          <p className="text-xs text-ore-500">
            {trend?.unit ? `Units: ${trend.unit}` : 'Units: —'} · {filterSummary}
          </p>
          {loading ? (
            <p className="mt-3 text-sm text-ore-400">Loading analytics...</p>
          ) : error && chartsTouched ? (
            <p className="mt-3 text-sm text-signal-red">Unable to load analytics.</p>
          ) : trend?.insufficient || (trend && !trendData.length) ? (
            <p className="mt-3 text-sm text-ore-400">
              {trend?.message || 'No analytics data available for this selection.'}
            </p>
          ) : trend && trendData.length ? (
            <div className="mt-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <Chart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#314038" />
                  <XAxis dataKey="year" tick={{ fill: '#8a9e92', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#8a9e92', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1c2420', border: '1px solid #4a5c52', borderRadius: 8 }}
                  />
                  {chartKind === 'bar' ? (
                    <Bar dataKey="value" fill="#c8843a" radius={[4, 4, 0, 0]} />
                  ) : (
                    <Line type="monotone" dataKey="value" stroke="#c8843a" strokeWidth={2} dot />
                  )}
                </Chart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-3 text-sm text-ore-500">Generate analysis to see trends.</p>
          )}
          <p className="mt-2 text-xs uppercase tracking-wide text-ore-500">Source / Provenance</p>
          <ProvenanceList items={trend?.provenance || []} />
        </section>

        {!isGeological ? (
        <section className="panel rounded-lg p-5">
          <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Actual vs Target</h2>
          <p className="text-xs text-ore-500">{filterSummary}</p>
          {loading ? (
            <p className="mt-3 text-sm text-ore-400">Loading analytics...</p>
          ) : avt?.insufficient || !avt ? (
            <p className="mt-3 text-sm text-ore-400">
              {avt?.message || 'No analytics data available for this selection.'}
            </p>
          ) : (
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
              {avt.data?.length ? (
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
              ) : null}
            </>
          )}
          <p className="mt-2 text-xs uppercase tracking-wide text-ore-500">Source / Provenance</p>
          <ProvenanceList items={avt?.provenance || []} />
        </section>
        ) : null}

        <section className="panel rounded-lg p-5 lg:col-span-2">
          <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Data table</h2>
          <p className="text-xs text-ore-500">{filterSummary}</p>
          {loading ? (
            <p className="mt-3 text-sm text-ore-400">Loading analytics...</p>
          ) : !table.length ? (
            <p className="mt-3 text-sm text-ore-400">No analytics data available for this selection.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-sm">
                <thead>
                  <tr className="border-b border-ore-700/60 text-xs uppercase tracking-wide text-ore-500">
                    <th className="px-3 py-2">Period</th>
                    {table.some((r) => r.actual != null) ? <th className="px-3 py-2">Actual</th> : null}
                    {table.some((r) => r.target != null) ? <th className="px-3 py-2">Target</th> : null}
                    {table.some((r) => r.unit) ? <th className="px-3 py-2">Unit</th> : null}
                    <th className="px-3 py-2">Source</th>
                    <th className="px-3 py-2">Page</th>
                  </tr>
                </thead>
                <tbody>
                  {table.map((r) => (
                    <tr key={r.period} className="border-b border-ore-800/50">
                      <td className="px-3 py-2 text-ore-100">{r.period}</td>
                      {table.some((x) => x.actual != null) ? (
                        <td className="px-3 py-2 text-copper-300">{r.actual ?? '—'}</td>
                      ) : null}
                      {table.some((x) => x.target != null) ? (
                        <td className="px-3 py-2 text-ore-200">{r.target ?? '—'}</td>
                      ) : null}
                      {table.some((x) => x.unit) ? (
                        <td className="px-3 py-2 text-ore-400">{r.unit || '—'}</td>
                      ) : null}
                      <td className="px-3 py-2">
                        {r.document_id ? (
                          <Link
                            to={`/documents/${r.document_id}${r.page != null ? `#page-${r.page}` : ''}`}
                            className="text-copper-400 hover:text-copper-300"
                          >
                            {r.source || r.document_id}
                          </Link>
                        ) : (
                          <span className="text-ore-500">{r.evidence_note || 'Evidence unavailable'}</span>
                        )}
                        {r.document_id ? (
                          <>
                            {' · '}
                            <a
                              href={documentFileUrl(r.document_id, r.page)}
                              target="_blank"
                              rel="noreferrer"
                              className="text-ore-400 hover:text-ore-200"
                            >
                              file
                            </a>
                          </>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-ore-400">{r.page ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {compareResult ? (
          <section className="panel rounded-lg p-5 lg:col-span-2">
            <h2 className="mb-1 font-display text-xl uppercase tracking-wide text-ore-100">Entity Comparison</h2>
            {compareResult.insufficient || !compareResult.data?.length ? (
              <p className="mt-3 text-sm text-ore-400">
                {compareResult.message || 'No analytics data available for this selection.'}
              </p>
            ) : (
              <div className="mt-3 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={compareResult.data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#314038" />
                    <XAxis dataKey="entity" tick={{ fill: '#8a9e92', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#8a9e92', fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ background: '#1c2420', border: '1px solid #4a5c52', borderRadius: 8 }}
                    />
                    <Legend />
                    <Bar dataKey="value" name={compareResult.metric} fill="#c8843a" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <ProvenanceList items={compareResult.provenance || []} />
          </section>
        ) : null}
      </div>
    </div>
  )
}
