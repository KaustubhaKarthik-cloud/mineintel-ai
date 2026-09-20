import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { displayFileType, documentFileUrl, formatDate, getDocuments } from '../lib/api'
import type { DocumentItem } from '../types'
import { PageHeader, StatusBadge } from '../components/ui'

export function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getDocuments()
      .then(setDocs)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <PageHeader
        title="Documents"
        subtitle="Ingested mining documents with Phase 2 text extraction status. Open a row to inspect page/sheet evidence."
        action={
          <Link
            to="/upload"
            className="rounded-md bg-copper-500 px-4 py-2.5 text-sm font-semibold text-ore-950 hover:bg-copper-400"
          >
            Upload
          </Link>
        }
      />

      {loading ? <p className="text-ore-400">Loading documents…</p> : null}
      {error ? <p className="mb-4 text-sm text-signal-red">{error}</p> : null}

      {!loading && !error && docs.length === 0 ? (
        <div className="panel rounded-lg p-8 text-center animate-fade-up">
          <p className="text-ore-300">No documents yet.</p>
          <p className="mt-1 text-sm text-ore-500">
            Upload a PDF, Excel, or image — or use files in documents/demo/.
          </p>
          <Link to="/upload" className="mt-4 inline-block text-sm font-medium text-copper-400 hover:text-copper-300">
            Go to Upload →
          </Link>
        </div>
      ) : null}

      {docs.length > 0 ? (
        <div className="panel overflow-x-auto rounded-lg animate-fade-up">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead>
              <tr className="border-b border-ore-700/50 text-xs uppercase tracking-[0.12em] text-ore-500">
                <th className="px-4 py-3 font-medium">Document</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Uploaded</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Version</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-b border-ore-800/70 hover:bg-ore-850/40">
                  <td className="px-4 py-3">
                    <p className="font-medium text-ore-100">{d.original_filename}</p>
                    <p className="text-xs text-ore-500">
                      {d.mine_name ?? '—'} · {d.page_count} {d.file_type === 'excel' ? 'sheets' : 'pages'}
                    </p>
                  </td>
                  <td className="px-4 py-3 text-ore-300">{displayFileType(d)}</td>
                  <td className="px-4 py-3 text-ore-400">{formatDate(d.upload_date ?? d.created_at)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={d.status} />
                    {d.error_message ? (
                      <p className="mt-1 max-w-xs text-xs text-signal-red">{d.error_message}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-ore-400">v{d.version ?? 1}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-3">
                      <Link
                        to={`/documents/${d.id}`}
                        className="text-xs font-semibold uppercase tracking-wide text-copper-400 hover:text-copper-300"
                      >
                        Open
                      </Link>
                      <a
                        href={documentFileUrl(d.id)}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-semibold uppercase tracking-wide text-ore-400 hover:text-ore-200"
                      >
                        File
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
