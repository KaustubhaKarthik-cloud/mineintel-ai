import { useEffect, useState } from 'react'
import { ApiError, getSystemStatus } from '../lib/api'
import { PageHeader } from '../components/ui'

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="panel rounded-lg p-5">
      <h2 className="font-display text-lg uppercase tracking-wide text-ore-100">{title}</h2>
      <div className="mt-3 space-y-2">{children}</div>
    </section>
  )
}

function Row({ label, value, readOnly }: { label: string; value: string; readOnly?: boolean }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ore-800/60 py-2 last:border-0">
      <p className="text-xs uppercase tracking-[0.12em] text-ore-500">
        {label}
        {readOnly ? <span className="ml-2 text-[10px] normal-case tracking-normal text-ore-600">(read-only)</span> : null}
      </p>
      <p className="text-sm text-ore-200">{value}</p>
    </div>
  )
}

export function SettingsPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getSystemStatus()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Unable to load settings.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-ore-400">Loading system status…</p>
  if (error || !data) {
    return <p className="text-signal-red">{error || 'Unable to load settings. Check the backend connection.'}</p>
  }

  const app = (data.application || {}) as Record<string, unknown>
  const ai = (data.ai_assistant || {}) as Record<string, unknown>
  const proc = (data.document_processing || {}) as Record<string, unknown>
  const sys = (data.system || {}) as Record<string, unknown>
  const sec = (data.security || {}) as Record<string, unknown>
  const tech = (data.technical_details || {}) as Record<string, unknown>
  const vector = (sys.vector_index || {}) as Record<string, unknown>
  const storage = (sys.storage || {}) as Record<string, unknown>

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Live application, AI, processing, and system status. Controls that cannot change values are marked read-only."
      />

      <div className="mx-auto grid max-w-3xl gap-4 animate-fade-up">
        <Section title="Application">
          <Row label="Name" value={String(app.name || '—')} readOnly />
          <Row label="Version" value={String(app.version || '—')} readOnly />
          <Row label="Environment" value={String(app.environment || '—')} readOnly />
          <Row label="Status" value={String(app.status || '—')} readOnly />
          <Row label="Demo mode" value={String(app.demo_mode)} readOnly />
        </Section>

        <Section title="AI / Assistant">
          <Row label="Provider" value={String(ai.provider || '—')} readOnly />
          <Row label="Model" value={String(ai.model || '—')} readOnly />
          <Row label="Local enabled" value={String(ai.local_enabled)} readOnly />
          <Row label="Connection health" value={String(ai.connection_health || '—')} readOnly />
          <Row label="API key configured" value={String(ai.api_key_configured)} readOnly />
          {ai.message ? (
            <p className="mt-2 rounded-md border border-signal-amber/40 bg-signal-amber/10 px-3 py-2 text-sm text-signal-amber">
              {String(ai.message)}
            </p>
          ) : null}
        </Section>

        <Section title="Document processing">
          <Row label="OCR" value={`${proc.ocr_engine} (${proc.ocr_language})`} readOnly />
          <Row label="Supported types" value={(proc.supported_types as string[])?.join(', ') || '—'} readOnly />
          <Row label="Documents" value={String(proc.documents ?? '—')} readOnly />
          <Row label="Indexed documents" value={String(proc.indexed_documents ?? '—')} readOnly />
          <Row label="Extracted facts" value={String(proc.extracted_facts ?? '—')} readOnly />
        </Section>

        <Section title="System">
          <Row label="Database" value={`${sys.database} · ${sys.database_status}`} readOnly />
          <Row
            label="Vector index"
            value={`${vector.active_chunks ?? 0} chunks · ${vector.structured_facts ?? 0} structured · ${vector.embedding_provider}`}
            readOnly
          />
          <Row label="Storage" value={`${storage.status} · ${storage.path}`} readOnly />
          <Row label="Reports stored" value={String(sys.reports ?? 0)} readOnly />
        </Section>

        <Section title="Security">
          <Row label="Auth mode" value={String(sec.auth_mode || '—')} readOnly />
          <Row label="Current user" value={String(sec.current_user || '—')} readOnly />
          <Row label="Role" value={String(sec.role || '—')} readOnly />
          <Row
            label="Your permissions"
            value={(sec.permissions as string[])?.join(', ') || '—'}
            readOnly
          />
          {sec.roles && typeof sec.roles === 'object' ? (
            <div className="mt-3 space-y-2">
              <p className="text-xs uppercase tracking-[0.12em] text-ore-500">Role matrix (read-only)</p>
              {Object.entries(sec.roles as Record<string, string[]>).map(([role, perms]) => (
                <div key={role} className="rounded border border-ore-800 bg-ore-900/40 px-3 py-2">
                  <p className="text-sm font-medium uppercase tracking-wide text-copper-300">{role}</p>
                  <p className="mt-1 text-xs text-ore-400">{perms.join(', ')}</p>
                </div>
              ))}
            </div>
          ) : null}
          <p className="mt-2 text-xs text-ore-500">{String(sec.note || '')}</p>
          <p className="text-xs text-ore-500">
            Manage users under Users. Inspect audit events under Audit Logs.
          </p>
        </Section>

        <Section title="Technical details">
          <Row label="Extraction provider" value={String(tech.llm_extraction_provider || '—')} readOnly />
          <Row label="Chunk size" value={String(tech.chunk_size ?? '—')} readOnly />
          <Row label="Search top-k" value={String(tech.search_top_k ?? '—')} readOnly />
          <Row label="Min similarity" value={String(tech.min_similarity_threshold ?? '—')} readOnly />
          <Row label="Index verified facts" value={String(tech.index_verified_facts)} readOnly />
        </Section>
      </div>
    </div>
  )
}
