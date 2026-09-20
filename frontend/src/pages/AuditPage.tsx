import { useEffect, useState } from 'react'
import { ApiError, formatDate, getAuditLogs } from '../lib/api'
import { PageHeader } from '../components/ui'

type AuditRow = {
  id: string
  action: string
  entity_type?: string | null
  entity_id?: string | null
  actor?: string | null
  details?: Record<string, unknown> | null
  created_at?: string | null
}

export function AuditPage() {
  const [logs, setLogs] = useState<AuditRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getAuditLogs()
      .then((res) => setLogs(res.items))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Unable to load audit logs.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <PageHeader
        title="Audit Logs"
        subtitle="Immutable trail of uploads, extractions, reviews, indexing, and report events from the database."
      />
      {error ? (
        <p className="mb-4 text-sm text-signal-red">
          {error}
          {error.toLowerCase().includes('permission') || error.toLowerCase().includes('forbidden')
            ? ' Sign in as admin to view audit logs.'
            : ''}
        </p>
      ) : null}
      {loading ? <p className="text-ore-400">Loading audit logs…</p> : null}
      {!loading && !error && logs.length === 0 ? (
        <p className="text-sm text-ore-500">No audit events recorded yet.</p>
      ) : null}
      {!loading && logs.length > 0 ? (
        <div className="panel overflow-x-auto rounded-lg animate-fade-up">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="border-b border-ore-700/50 text-xs uppercase tracking-[0.12em] text-ore-500">
                <th className="px-4 py-3 font-medium">When</th>
                <th className="px-4 py-3 font-medium">Action</th>
                <th className="px-4 py-3 font-medium">Entity</th>
                <th className="px-4 py-3 font-medium">Actor</th>
                <th className="px-4 py-3 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-ore-800/70">
                  <td className="px-4 py-3 text-xs text-ore-500">{formatDate(l.created_at)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-copper-300">{l.action}</td>
                  <td className="px-4 py-3 text-ore-300">
                    {l.entity_type}
                    {l.entity_id ? ` / ${l.entity_id.slice(0, 8)}…` : ''}
                  </td>
                  <td className="px-4 py-3 text-ore-300">{l.actor || '—'}</td>
                  <td className="px-4 py-3 text-xs text-ore-500">
                    {l.details ? JSON.stringify(l.details) : '—'}
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
