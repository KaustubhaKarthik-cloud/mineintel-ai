import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Download, ExternalLink } from 'lucide-react'
import { ApiError, downloadReportFile, formatDate, getReport, reportViewUrl, type ReportItem } from '../lib/api'
import { PageHeader, StatusBadge } from '../components/ui'

export function ReportDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [report, setReport] = useState<ReportItem | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [downloadError, setDownloadError] = useState('')

  useEffect(() => {
    if (!id) return
    setLoading(true)
    getReport(id)
      .then(setReport)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Unable to load report.'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <p className="text-ore-400">Loading report…</p>
  if (error || !report) {
    return (
      <div>
        <p className="text-signal-red">{error || 'Report not found.'}</p>
        <Link to="/reports" className="mt-4 inline-block text-sm text-copper-400">
          ← Back to reports
        </Link>
      </div>
    )
  }

  const params = report.parameters || {}

  return (
    <div>
      <Link
        to="/reports"
        className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ore-400 hover:text-copper-300"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Reports
      </Link>

      <PageHeader
        title={report.title}
        subtitle={`${report.report_type} · ${formatDate(report.created_at)}${
          report.generated_by ? ` · ${report.generated_by}` : ''
        }`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={report.status} />
            <a
              href={reportViewUrl(report.id)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md bg-ore-800 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-ore-100 ring-1 ring-ore-600 hover:bg-ore-700"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Full page
            </a>
            <button
              type="button"
              onClick={() => {
                setDownloadError('')
                downloadReportFile(report.id, report.title).catch((e) =>
                  setDownloadError(e instanceof ApiError ? e.message : 'Download failed'),
                )
              }}
              className="inline-flex items-center gap-1.5 rounded-md bg-copper-500 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-ore-950 hover:bg-copper-400"
            >
              <Download className="h-3.5 w-3.5" /> Download
            </button>
          </div>
        }
      />

      {downloadError ? <p className="mb-3 text-sm text-signal-red">{downloadError}</p> : null}

      <div className="mb-4 flex flex-wrap gap-2 text-xs">
        {params.entity ? (
          <span className="rounded-full bg-copper-500/15 px-3 py-1 text-copper-300 ring-1 ring-copper-500/30">
            Entity · {String(params.entity)}
          </span>
        ) : null}
        {params.metric ? (
          <span className="rounded-full bg-ore-800 px-3 py-1 text-ore-300 ring-1 ring-ore-600">
            Metric · {String(params.metric)}
          </span>
        ) : null}
        {params.period ? (
          <span className="rounded-full bg-ore-800 px-3 py-1 text-ore-300 ring-1 ring-ore-600">
            Period · {String(params.period)}
          </span>
        ) : null}
        {report.source_documents?.length ? (
          <span className="rounded-full bg-ore-800 px-3 py-1 text-ore-300 ring-1 ring-ore-600">
            {report.source_documents.length} source doc{report.source_documents.length === 1 ? '' : 's'}
          </span>
        ) : null}
      </div>

      {report.source_documents?.length ? (
        <p className="mb-4 text-xs text-ore-500">Sources: {report.source_documents.join(', ')}</p>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-ore-700/60 bg-ore-950 shadow-lg shadow-black/20">
        <iframe
          title={report.title}
          src={reportViewUrl(report.id)}
          className="h-[75vh] w-full border-0 bg-[#121816]"
        />
      </div>
    </div>
  )
}
