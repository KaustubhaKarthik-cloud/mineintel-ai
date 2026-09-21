import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ApiError,
  documentFileUrl,
  explainGeologyAnalytics,
  getGeologyAnalytics,
  getGeologyCompare,
  getGeologyExplorer,
  getGeologyFact,
} from '../lib/api'
import { PageHeader, StatusBadge } from '../components/ui'

type Tab = 'facts' | 'formations' | 'seams' | 'boreholes' | 'analytics' | 'compare'

function EmptyState({ message }: { message: string }) {
  return (
    <p className="rounded border border-ore-800 bg-ore-900/50 px-4 py-6 text-center text-sm text-ore-400">
      {message}
    </p>
  )
}

function PendingBanner({ show }: { show?: boolean }) {
  if (!show) return null
  return (
    <p className="mb-3 rounded border border-signal-amber/40 bg-signal-amber/10 px-3 py-2 text-xs text-signal-amber">
      Data available but pending human verification. These facts are not silently treated as verified.
    </p>
  )
}

function EvidencePanel({
  item,
  onClose,
}: {
  item: Record<string, unknown> | null
  onClose: () => void
}) {
  if (!item) return null
  const docId = String(item.document_id || item.source_document_id || '')
  const page = item.page != null ? Number(item.page) : item.source_page != null ? Number(item.source_page) : null
  const requires = Boolean(item.requires_human_verification)
  return (
    <aside className="panel sticky top-4 rounded-lg p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <h3 className="font-display text-lg uppercase tracking-wide text-ore-100">Evidence</h3>
        <button type="button" className="text-xs text-ore-400 hover:text-ore-200" onClick={onClose}>
          Close
        </button>
      </div>
      {requires ? (
        <p className="mb-3 rounded border border-signal-amber/40 bg-signal-amber/10 px-2 py-1.5 text-xs text-signal-amber">
          Requires human verification
        </p>
      ) : null}
      <dl className="space-y-2 text-sm">
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-ore-500">Entity / metric</dt>
          <dd className="text-ore-100">
            {[item.seam_label || item.seam || item.formation_name || item.formation || item.borehole_id, item.metric_kind]
              .filter(Boolean)
              .join(' · ') || '—'}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-ore-500">Value</dt>
          <dd className="text-copper-300">
            {String(item.display_value ?? item.value ?? item.original_value ?? '—')}
            {item.display_unit || item.unit ? ` ${item.display_unit || item.unit}` : ''}
          </dd>
        </div>
        {item.corrected_value ? (
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-ore-500">Corrected</dt>
            <dd className="text-signal-blue">
              {String(item.corrected_value)}
              {item.corrected_unit ? ` ${item.corrected_unit}` : ''}
            </dd>
            <dd className="mt-1 text-xs text-ore-500">
              Original: {String(item.original_extracted_value ?? item.original_value ?? '—')}
            </dd>
          </div>
        ) : null}
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-ore-500">Status</dt>
          <dd>
            <StatusBadge status={String(item.status || item.review_status || item.review_bucket || 'extracted')} />
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-ore-500">Confidence</dt>
          <dd className="tabular-nums text-ore-300">
            {item.extraction_confidence != null || item.confidence != null
              ? `${Math.round(Number(item.extraction_confidence ?? item.confidence) * 100)}%`
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-ore-500">Provenance</dt>
          <dd className="text-ore-300">
            {docId ? (
              <Link
                to={`/documents/${docId}${page != null ? `#page-${page}` : ''}`}
                className="text-copper-400 hover:text-copper-300"
              >
                {String(item.document_name || docId)}
                {page != null ? ` · p.${page}` : ''}
              </Link>
            ) : (
              String(item.document_name || '—')
            )}
            {docId ? (
              <>
                {' · '}
                <a
                  href={documentFileUrl(docId, page)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-ore-400 hover:text-ore-200"
                >
                  open file
                </a>
              </>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-ore-500">Source evidence</dt>
          <dd className="mt-1 max-h-48 overflow-y-auto rounded bg-ore-900/60 p-2 text-xs leading-relaxed text-ore-300">
            {String(item.evidence_text || (item.provenance as { evidence_text?: string } | undefined)?.evidence_text || '—')}
          </dd>
        </div>
      </dl>
    </aside>
  )
}

function AnalyticChart({
  title,
  data,
  emptyMessage,
  pending,
  xKey,
  onSelect,
}: {
  title: string
  data: Array<Record<string, unknown>>
  emptyMessage: string
  pending?: boolean
  xKey: string
  onSelect: (row: Record<string, unknown>) => void
}) {
  const chartData = useMemo(
    () =>
      data.map((row) => {
        const raw = row.value
        const num = typeof raw === 'number' ? raw : Number(String(raw).split('–')[0])
        return {
          ...row,
          _label: String(row[xKey] ?? ''),
          _num: Number.isFinite(num) ? num : 0,
        }
      }),
    [data, xKey],
  )

  return (
    <section className="panel rounded-lg p-4">
      <h3 className="font-display text-lg uppercase tracking-wide text-ore-100">{title}</h3>
      <PendingBanner show={pending} />
      {!data.length ? (
        <EmptyState message={emptyMessage} />
      ) : (
        <>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#3d3a35" />
                <XAxis dataKey="_label" tick={{ fill: '#a39e94', fontSize: 11 }} />
                <YAxis tick={{ fill: '#a39e94', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#1c1a17', border: '1px solid #3d3a35' }}
                  labelStyle={{ color: '#e8e4dc' }}
                />
                <Bar dataKey="_num" fill="#c4783a" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="mt-3 w-full text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wide text-ore-500">
              <tr>
                <th className="py-1">Entity</th>
                <th>Value</th>
                <th>Page</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr
                  key={String(row.fact_id || i)}
                  className="cursor-pointer border-t border-ore-800/80 hover:bg-ore-850/60"
                  onClick={() => onSelect(row)}
                >
                  <td className="py-2 text-ore-100">{String(row[xKey] ?? '—')}</td>
                  <td className="text-copper-300">
                    {String(row.value ?? '—')}
                    {row.unit ? ` ${row.unit}` : ''}
                  </td>
                  <td className="text-ore-400">{row.page != null ? String(row.page) : '—'}</td>
                  <td>
                    <StatusBadge status={String(row.status || row.review_bucket || 'extracted')} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

export function GeologicalExplorerPage() {
  const [tab, setTab] = useState<Tab>('facts')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [explorer, setExplorer] = useState<Awaited<ReturnType<typeof getGeologyExplorer>> | null>(null)
  const [analytics, setAnalytics] = useState<Awaited<ReturnType<typeof getGeologyAnalytics>> | null>(null)
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null)

  const [documentId, setDocumentId] = useState('')
  const [formation, setFormation] = useState('')
  const [seam, setSeam] = useState('')
  const [borehole, setBorehole] = useState('')
  const [metric, setMetric] = useState('')
  const [status, setStatus] = useState('')

  const [compareA, setCompareA] = useState('')
  const [compareB, setCompareB] = useState('')
  const [compare, setCompare] = useState<Awaited<ReturnType<typeof getGeologyCompare>> | null>(null)
  const [explainQ, setExplainQ] = useState('Explain the resource distribution shown here.')
  const [explanation, setExplanation] = useState('')
  const [explainLoading, setExplainLoading] = useState(false)

  const filterParams = useMemo(
    () => ({
      document_id: documentId || undefined,
      formation: formation || undefined,
      seam: seam || undefined,
      borehole: borehole || undefined,
      metric: metric || undefined,
      status: status || undefined,
    }),
    [documentId, formation, seam, borehole, metric, status],
  )

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [ex, an] = await Promise.all([
          getGeologyExplorer(filterParams),
          getGeologyAnalytics({
            document_id: documentId || undefined,
            formation: formation || undefined,
            seam: seam || undefined,
          }),
        ])
        if (!cancelled) {
          setExplorer(ex)
          setAnalytics(an)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : 'Unable to load geological explorer.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [filterParams, documentId, formation, seam])

  async function openFact(factId: string) {
    try {
      const detail = await getGeologyFact(factId)
      setSelected(detail)
    } catch {
      /* ignore */
    }
  }

  async function runCompare() {
    if (!compareA || !compareB || compareA === compareB) return
    setError('')
    try {
      setCompare(await getGeologyCompare(compareA, compareB))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Compare failed.')
    }
  }

  async function runExplain() {
    setExplainLoading(true)
    setExplanation('')
    try {
      const res = await explainGeologyAnalytics({
        question: explainQ,
        analytic: 'resources_by_seam',
        document_id: documentId || undefined,
        formation: formation || undefined,
        seam: seam || undefined,
        evidence: analytics?.resources_by_seam,
      })
      setExplanation(res.explanation)
    } catch (e) {
      setExplanation(e instanceof ApiError ? e.message : 'Explanation failed.')
    } finally {
      setExplainLoading(false)
    }
  }

  const filters = explorer?.filters
  const summary = explorer?.summary
  const docs = filters?.documents || []

  return (
    <div>
      <PageHeader
        title="Geological Explorer"
        subtitle="Evidence-grounded exploration and analytics from structured geological facts — charts never invent numbers."
      />

      <div className="panel mb-4 rounded-lg p-4">
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
          <label className="text-xs text-ore-400">
            Document
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
            >
              <option value="">All geological documents</option>
              {docs.map((d) => (
                <option key={String(d.document_id)} value={String(d.document_id)}>
                  {String(d.document_name || d.document_id)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ore-400">
            Formation
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={formation}
              onChange={(e) => setFormation(e.target.value)}
            >
              <option value="">All</option>
              {(filters?.formations || []).map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ore-400">
            Seam
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={seam}
              onChange={(e) => setSeam(e.target.value)}
            >
              <option value="">All</option>
              {(filters?.seams || []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ore-400">
            Borehole
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={borehole}
              onChange={(e) => setBorehole(e.target.value)}
            >
              <option value="">All</option>
              {(filters?.boreholes || []).map((b) => (
                <option key={b} value={b}>
                  {b}
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
              {(filters?.metrics || []).map((m) => (
                <option key={m} value={m}>
                  {m.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ore-400">
            Status
            <select
              className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All (excl. rejected)</option>
              <option value="verified">Verified</option>
              <option value="review_required">Review required</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>
        </div>
      </div>

      {error ? <p className="mb-4 text-sm text-signal-red">{error}</p> : null}

      {summary ? (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['Facts', summary.fact_count],
            ['Formations', summary.formation_count],
            ['Seams', summary.seam_count],
            ['Boreholes', summary.borehole_count],
            ['Resources', summary.resource_fact_count],
            ['Review required', summary.review_required_count],
          ].map(([label, value]) => (
            <div key={String(label)} className="panel rounded-lg p-4">
              <p className="text-[11px] uppercase tracking-[0.14em] text-ore-400">{label}</p>
              <p className="mt-1 font-display text-2xl text-ore-100">{value != null ? String(value) : '0'}</p>
            </div>
          ))}
        </div>
      ) : null}

      {summary?.pending_verification ? <PendingBanner show /> : null}

      <div className="mb-4 flex flex-wrap gap-2">
        {(
          [
            ['facts', 'Geological facts'],
            ['formations', 'Formations'],
            ['seams', 'Seams'],
            ['boreholes', 'Boreholes'],
            ['analytics', 'Analytics'],
            ['compare', 'Compare'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
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

      {loading ? <p className="text-ore-400">Loading geological data…</p> : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-4">
          {tab === 'facts' && explorer ? (
            <section className="panel overflow-x-auto rounded-lg p-4">
              <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Geological facts</h2>
              {!explorer.facts.items.length ? (
                <EmptyState message="No compatible structured evidence available." />
              ) : (
                <table className="mt-3 w-full text-left text-sm">
                  <thead className="text-[11px] uppercase tracking-wide text-ore-500">
                    <tr>
                      <th className="py-1">Entity</th>
                      <th>Metric</th>
                      <th>Value</th>
                      <th>Page</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {explorer.facts.items.map((f) => (
                      <tr
                        key={String(f.id)}
                        className="cursor-pointer border-t border-ore-800/80 hover:bg-ore-850/60"
                        onClick={() => openFact(String(f.id))}
                      >
                        <td className="py-2 text-ore-100">
                          {String(f.seam_label || f.formation_name || f.borehole_id || '—')}
                        </td>
                        <td className="text-ore-400">{String(f.metric_kind || '—').replace(/_/g, ' ')}</td>
                        <td className="text-copper-300">
                          {String(f.display_value ?? '—')}
                          {f.display_unit ? ` ${f.display_unit}` : ''}
                        </td>
                        <td className="text-ore-400">{f.source_page != null ? String(f.source_page) : '—'}</td>
                        <td>
                          <StatusBadge status={String(f.status || 'extracted')} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          ) : null}

          {tab === 'formations' && explorer ? (
            <section className="panel rounded-lg p-4">
              <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Formations</h2>
              {!explorer.formations.length ? (
                <EmptyState message="No compatible structured evidence available." />
              ) : (
                <ul className="mt-3 space-y-2">
                  {explorer.formations.map((f) => (
                    <li
                      key={String(f.formation_name)}
                      className="cursor-pointer rounded border border-ore-800 bg-ore-900/40 px-3 py-2 hover:border-copper-500/40"
                      onClick={() => {
                        const id = (f.fact_ids as string[] | undefined)?.[0]
                        if (id) openFact(id)
                      }}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-ore-100">{String(f.formation_name)}</span>
                        <StatusBadge status={String(f.review_status || 'review_required')} />
                      </div>
                      <p className="mt-1 text-xs text-ore-400">
                        Seams: {(f.associated_seams as string[] | undefined)?.join(', ') || '—'}
                        {' · '}
                        Pages: {(f.source_pages as number[] | undefined)?.join(', ') || '—'}
                        {' · '}
                        Evidence: {String(f.evidence_count ?? 0)}
                      </p>
                      {f.requires_human_verification ? (
                        <p className="mt-1 text-[11px] text-signal-amber">Requires human verification</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : null}

          {tab === 'seams' && explorer ? (
            <section className="panel overflow-x-auto rounded-lg p-4">
              <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Seams</h2>
              {!explorer.seams.length ? (
                <EmptyState message="No compatible structured evidence available." />
              ) : (
                <table className="mt-3 w-full text-left text-sm">
                  <thead className="text-[11px] uppercase tracking-wide text-ore-500">
                    <tr>
                      <th className="py-1">Seam</th>
                      <th>Formation</th>
                      <th>Thickness</th>
                      <th>Resource</th>
                      <th>Page</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {explorer.seams.map((s) => (
                      <tr
                        key={`${s.document_id}-${s.seam_name}`}
                        className="cursor-pointer border-t border-ore-800/80 hover:bg-ore-850/60"
                        onClick={() => {
                          const id = (s.fact_ids as string[] | undefined)?.[0]
                          if (id) openFact(id)
                        }}
                      >
                        <td className="py-2 text-ore-100">{String(s.seam_name)}</td>
                        <td className="text-ore-400">{String(s.formation || '—')}</td>
                        <td className="text-copper-300">
                          {s.thickness
                            ? `${s.thickness}${s.thickness_unit ? ` ${s.thickness_unit}` : ''}`
                            : '—'}
                        </td>
                        <td className="text-copper-300">
                          {s.resource
                            ? `${s.resource}${s.resource_unit ? ` ${s.resource_unit}` : ''}`
                            : '—'}
                        </td>
                        <td className="text-ore-400">
                          {(s.source_pages as number[] | undefined)?.join(', ') || '—'}
                        </td>
                        <td>
                          <StatusBadge status={String(s.review_status || 'review_required')} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          ) : null}

          {tab === 'boreholes' && explorer ? (
            <section className="panel overflow-x-auto rounded-lg p-4">
              <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Boreholes</h2>
              {!explorer.boreholes.length ? (
                <EmptyState message="No compatible structured evidence available." />
              ) : (
                <table className="mt-3 w-full text-left text-sm">
                  <thead className="text-[11px] uppercase tracking-wide text-ore-500">
                    <tr>
                      <th className="py-1">Borehole</th>
                      <th>Depth</th>
                      <th>Seams</th>
                      <th>Formation</th>
                      <th>Page</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {explorer.boreholes.map((b) => (
                      <tr
                        key={`${b.document_id}-${b.borehole_id}`}
                        className="cursor-pointer border-t border-ore-800/80 hover:bg-ore-850/60"
                        onClick={() => {
                          const id = (b.fact_ids as string[] | undefined)?.[0]
                          if (id) openFact(id)
                        }}
                      >
                        <td className="py-2 text-ore-100">{String(b.borehole_id)}</td>
                        <td className="text-copper-300">
                          {b.depth ? `${b.depth}${b.depth_unit ? ` ${b.depth_unit}` : ''}` : '—'}
                        </td>
                        <td className="text-ore-400">
                          {(b.associated_seams as string[] | undefined)?.join(', ') || '—'}
                        </td>
                        <td className="text-ore-400">
                          {(b.formations as string[] | undefined)?.join(', ') || '—'}
                        </td>
                        <td className="text-ore-400">
                          {(b.source_pages as number[] | undefined)?.join(', ') || '—'}
                        </td>
                        <td>
                          <StatusBadge status={String(b.review_status || 'review_required')} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          ) : null}

          {tab === 'analytics' && analytics ? (
            <div className="space-y-4">
              <section className="panel rounded-lg p-4">
                <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">
                  Geological fact summary
                </h2>
                <PendingBanner show={Boolean(analytics.summary.pending_verification)} />
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  {Object.entries(analytics.summary)
                    .filter(([k]) =>
                      [
                        'formations_identified',
                        'seams_identified',
                        'boreholes_identified',
                        'resources_available',
                        'review_required_facts',
                        'documents_represented',
                      ].includes(k),
                    )
                    .map(([k, v]) => (
                      <div key={k} className="rounded bg-ore-900/50 px-3 py-2">
                        <p className="text-[11px] uppercase tracking-wide text-ore-500">
                          {k.replace(/_/g, ' ')}
                        </p>
                        <p className="font-display text-xl text-ore-100">{String(v)}</p>
                      </div>
                    ))}
                </div>
              </section>

              <AnalyticChart
                title="Resource by seam"
                data={analytics.resources_by_seam.items}
                emptyMessage={
                  analytics.resources_by_seam.message ||
                  'No compatible structured evidence available.'
                }
                pending={analytics.resources_by_seam.pending_verification}
                xKey="seam"
                onSelect={(row) => {
                  if (row.fact_id) openFact(String(row.fact_id))
                  else setSelected(row)
                }}
              />

              <section className="panel rounded-lg p-4">
                <h3 className="font-display text-lg uppercase tracking-wide text-ore-100">
                  Formation → Seam
                </h3>
                <PendingBanner show={analytics.formation_seam.pending_verification} />
                {!analytics.formation_seam.items.length ? (
                  <EmptyState
                    message={
                      analytics.formation_seam.message ||
                      'No compatible structured evidence available.'
                    }
                  />
                ) : (
                  <ul className="mt-3 space-y-3">
                    {analytics.formation_seam.items.map((f) => (
                      <li key={String(f.formation)}>
                        <p className="font-medium text-ore-100">{String(f.formation)}</p>
                        <ul className="mt-1 space-y-1 border-l border-ore-700 pl-3">
                          {((f.seams as Array<Record<string, unknown>>) || []).map((s) => (
                            <li key={String(s.seam)} className="text-sm text-ore-300">
                              <button
                                type="button"
                                className="text-left hover:text-copper-300"
                                onClick={() => {
                                  const id = (s.fact_ids as string[] | undefined)?.[0]
                                  if (id) openFact(id)
                                }}
                              >
                                {String(s.seam)}
                                {s.source_pages
                                  ? ` · p.${(s.source_pages as number[]).join(', ')}`
                                  : ''}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <AnalyticChart
                title="Borehole depth"
                data={analytics.borehole_depths.items}
                emptyMessage={
                  analytics.borehole_depths.message ||
                  'No compatible structured evidence available.'
                }
                pending={analytics.borehole_depths.pending_verification}
                xKey="borehole_id"
                onSelect={(row) => {
                  if (row.fact_id) openFact(String(row.fact_id))
                  else setSelected(row)
                }}
              />

              <AnalyticChart
                title="Seam thickness"
                data={analytics.seam_thickness.items}
                emptyMessage={
                  analytics.seam_thickness.message ||
                  'No compatible seam-thickness evidence available.'
                }
                pending={analytics.seam_thickness.pending_verification}
                xKey="seam"
                onSelect={(row) => {
                  if (row.fact_id) openFact(String(row.fact_id))
                  else setSelected(row)
                }}
              />

              <section className="panel rounded-lg p-4">
                <h3 className="font-display text-lg uppercase tracking-wide text-ore-100">
                  AI explanation
                </h3>
                <p className="mt-1 text-xs text-ore-500">
                  Qwen explains only the structured evidence already shown — it does not invent chart values.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <input
                    className="min-w-[240px] flex-1 rounded border border-ore-700 bg-ore-900 px-3 py-2 text-sm text-ore-100"
                    value={explainQ}
                    onChange={(e) => setExplainQ(e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={runExplain}
                    disabled={explainLoading}
                    className="rounded-md bg-copper-500/20 px-4 py-2 text-sm font-medium text-copper-300 ring-1 ring-copper-500/40 hover:bg-copper-500/30 disabled:opacity-50"
                  >
                    {explainLoading ? 'Explaining…' : 'Explain'}
                  </button>
                </div>
                {explanation ? (
                  <pre className="mt-3 whitespace-pre-wrap rounded bg-ore-900/60 p-3 text-sm text-ore-200">
                    {explanation}
                  </pre>
                ) : null}
              </section>
            </div>
          ) : null}

          {tab === 'compare' ? (
            <section className="panel rounded-lg p-4">
              <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">
                Document comparison
              </h2>
              <p className="mt-1 text-xs text-ore-500">
                Factual side-by-side comparison only — documents are not ranked.
              </p>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                <label className="text-xs text-ore-400">
                  Document A
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={compareA}
                    onChange={(e) => setCompareA(e.target.value)}
                  >
                    <option value="">Select…</option>
                    {docs.map((d) => (
                      <option key={String(d.document_id)} value={String(d.document_id)}>
                        {String(d.document_name || d.document_id)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-ore-400">
                  Document B
                  <select
                    className="mt-1 w-full rounded border border-ore-700 bg-ore-900 px-2 py-2 text-sm text-ore-100"
                    value={compareB}
                    onChange={(e) => setCompareB(e.target.value)}
                  >
                    <option value="">Select…</option>
                    {docs.map((d) => (
                      <option key={String(d.document_id)} value={String(d.document_id)}>
                        {String(d.document_name || d.document_id)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex items-end">
                  <button
                    type="button"
                    onClick={runCompare}
                    className="w-full rounded-md bg-copper-500/20 px-4 py-2 text-sm font-medium text-copper-300 ring-1 ring-copper-500/40"
                  >
                    Compare
                  </button>
                </div>
              </div>
              {compare ? (
                <div className="mt-4 space-y-3">
                  <p className="text-xs text-ore-500">{compare.note}</p>
                  {compare.comparisons.map((c) => (
                    <div key={String(c.metric)} className="rounded border border-ore-800 bg-ore-900/40 p-3">
                      <p className="text-sm font-medium uppercase tracking-wide text-copper-300">
                        {String(c.metric).replace(/_/g, ' ')}
                      </p>
                      <div className="mt-2 grid gap-3 md:grid-cols-2 text-xs text-ore-300">
                        <div>
                          <p className="text-ore-500">{String(compare.document_a.document_name)}</p>
                          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">
                            {JSON.stringify(c.document_a, null, 2)}
                          </pre>
                        </div>
                        <div>
                          <p className="text-ore-500">{String(compare.document_b.document_name)}</p>
                          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">
                            {JSON.stringify(c.document_b, null, 2)}
                          </pre>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}
        </div>

        <EvidencePanel item={selected} onClose={() => setSelected(null)} />
      </div>
    </div>
  )
}
