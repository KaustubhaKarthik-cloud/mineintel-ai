import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  FileText,
  ClipboardCheck,
  CheckCircle2,
  Gauge,
  ArrowRight,
  Activity,
} from 'lucide-react'
import { getDashboard } from '../lib/api'
import type { DashboardStats } from '../types'
import { ConfidenceBar, PageHeader, StatusBadge } from '../components/ui'

export function DashboardPage() {
  const [data, setData] = useState<DashboardStats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Unable to load dashboard.'))
  }, [])

  if (error && !data) {
    return <p className="text-signal-red">Unable to load dashboard. Check the backend connection.</p>
  }

  if (!data) {
    return <p className="text-ore-400 animate-fade-in">Loading operations overview…</p>
  }

  const kpis = [
    { label: 'Documents', value: data.total_documents, icon: FileText, hint: 'In corpus' },
    { label: 'Pending Review', value: data.pending_review, icon: ClipboardCheck, hint: 'Human queue' },
    { label: 'Approved', value: data.approved_records, icon: CheckCircle2, hint: 'Validated records' },
    { label: 'Avg Confidence', value: `${Math.round(data.avg_confidence * 100)}%`, icon: Gauge, hint: 'Extraction quality' },
  ]

  return (
    <div>
      <PageHeader
        title="Operations Dashboard"
        subtitle="Dual-pipeline status: structured extraction with human review, plus RAG-ready document intelligence."
        action={
          <Link
            to="/upload"
            className="inline-flex items-center gap-2 rounded-md bg-copper-500 px-4 py-2.5 text-sm font-semibold text-ore-950 transition hover:bg-copper-400"
          >
            Ingest document <ArrowRight className="h-4 w-4" />
          </Link>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((k, i) => (
          <div
            key={k.label}
            className="panel rounded-lg p-5 animate-fade-up"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div className="flex items-start justify-between">
              <p className="text-xs uppercase tracking-[0.16em] text-ore-400">{k.label}</p>
              <k.icon className="h-4 w-4 text-copper-400" />
            </div>
            <p className="mt-3 font-display text-4xl text-ore-100">{k.value}</p>
            <p className="mt-1 text-xs text-ore-500">{k.hint}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <section className="panel rounded-lg p-5 lg:col-span-3 animate-fade-up" style={{ animationDelay: '200ms' }}>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-xl uppercase tracking-wide text-ore-100">Recent documents</h2>
            <Link to="/documents" className="text-xs font-medium text-copper-400 hover:text-copper-300">
              View all
            </Link>
          </div>
          <div className="space-y-2">
            {data.recent_documents.map((doc) => (
              <div
                key={doc.id}
                className="panel-inset flex flex-wrap items-center justify-between gap-3 rounded-md px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ore-100">{doc.original_filename}</p>
                  <p className="mt-0.5 text-xs text-ore-500">
                    {doc.mine_name ?? '—'} · {doc.document_category}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  {doc.overall_confidence != null ? (
                    <ConfidenceBar value={doc.overall_confidence} />
                  ) : (
                    <span className="text-xs text-ore-500">Processing</span>
                  )}
                  <StatusBadge status={doc.status} />
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="panel rounded-lg p-5 lg:col-span-2 animate-fade-up" style={{ animationDelay: '280ms' }}>
          <h2 className="mb-4 font-display text-xl uppercase tracking-wide text-ore-100">Pipeline</h2>
          <ul className="space-y-3">
            {Object.entries(data.pipeline_status).map(([key, status]) => (
              <li key={key} className="flex items-center justify-between text-sm">
                <span className="capitalize text-ore-300">{key.replace(/_/g, ' ')}</span>
                <StatusBadge status={status} />
              </li>
            ))}
          </ul>

          <div className="mt-6 border-t border-ore-700/40 pt-4">
            <div className="mb-3 flex items-center gap-2">
              <Activity className="h-4 w-4 text-copper-400" />
              <h3 className="text-xs uppercase tracking-[0.16em] text-ore-400">Activity</h3>
            </div>
            <ul className="space-y-3">
              {data.recent_activity.map((a) => (
                <li key={a.id} className="text-sm">
                  <p className="font-medium text-ore-200">{a.action}</p>
                  <p className="text-xs text-ore-500">{a.detail}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </div>
  )
}
