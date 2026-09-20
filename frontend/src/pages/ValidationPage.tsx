import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Play, Check, X, Pencil } from 'lucide-react'
import {
  ApiError,
  confirmValidationConflict,
  dismissValidationConflict,
  getValidationConflicts,
  getValidationStats,
  resolveValidationConflict,
  runValidation,
} from '../lib/api'
import type { ValidationConflict, ValidationStats } from '../types'
import { PageHeader, StatusBadge } from '../components/ui'

export function ValidationPage() {
  const [stats, setStats] = useState<ValidationStats | null>(null)
  const [items, setItems] = useState<ValidationConflict[]>([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [running, setRunning] = useState(false)
  const [resolving, setResolving] = useState<string | null>(null)
  const [selectedValue, setSelectedValue] = useState('')
  const [selectedUnit, setSelectedUnit] = useState('')
  const [reason, setReason] = useState('')

  async function reload() {
    const [s, c] = await Promise.all([getValidationStats(), getValidationConflicts()])
    setStats(s)
    setItems(c.items)
  }

  useEffect(() => {
    reload().catch((e: Error) => setError(e.message))
  }, [])

  async function onRun() {
    setRunning(true)
    setError('')
    setMsg('Running validation…')
    try {
      const r = await runValidation()
      setMsg(
        `Done — scanned ${r.facts_scanned} facts, detected ${r.conflicts_detected} (` +
          `${r.created} new, ${r.refreshed} refreshed).`,
      )
      await reload()
    } catch (e) {
      setMsg('')
      setError(e instanceof ApiError ? e.message : 'Validation failed')
    } finally {
      setRunning(false)
    }
  }

  async function onConfirm(id: string) {
    await confirmValidationConflict(id)
    await reload()
  }

  async function onDismiss(id: string) {
    await dismissValidationConflict(id, reason || 'Dismissed — not a real conflict')
    setReason('')
    await reload()
  }

  async function onResolve(id: string) {
    if (!selectedValue.trim()) return
    await resolveValidationConflict(id, selectedValue.trim(), selectedUnit || undefined, reason || undefined)
    setResolving(null)
    setSelectedValue('')
    setSelectedUnit('')
    setReason('')
    await reload()
  }

  return (
    <div>
      <PageHeader
        title="Validation"
        subtitle="Cross-document contradiction detection and reported vs calculated discrepancy review. Humans decide — the system never auto-picks a side."
        action={
          <button
            type="button"
            disabled={running}
            onClick={onRun}
            className="inline-flex items-center gap-2 rounded-md bg-copper-500 px-4 py-2 text-sm font-semibold text-ore-950 hover:bg-copper-400 disabled:opacity-40"
          >
            <Play className="h-4 w-4" />
            {running ? 'Running…' : 'Run validation'}
          </button>
        }
      />

      {msg ? <p className="mb-3 text-sm text-signal-green">{msg}</p> : null}
      {error ? <p className="mb-3 text-sm text-signal-red">{error}</p> : null}

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5 animate-fade-up">
        {[
          { label: 'Facts', value: stats?.facts ?? '—' },
          { label: 'Validated', value: stats?.validated ?? '—' },
          { label: 'Review required', value: stats?.review_required ?? '—' },
          { label: 'Open conflicts', value: stats?.conflicts ?? '—' },
          { label: 'Resolved', value: stats?.resolved ?? '—' },
        ].map((row) => (
          <div key={row.label} className="panel rounded-lg px-4 py-3">
            <p className="text-[10px] uppercase tracking-[0.14em] text-ore-500">{row.label}</p>
            <p className="mt-1 font-display text-2xl text-ore-100">{row.value}</p>
          </div>
        ))}
      </div>

      <div className="space-y-4 animate-fade-up">
        {items.length === 0 ? (
          <div className="panel rounded-lg p-6 text-sm text-ore-400">
            No validation conflicts yet. Extract facts from multiple documents, then click{' '}
            <strong className="text-ore-200">Run validation</strong>.
          </div>
        ) : (
          items.map((c) => (
            <article key={c.id} className="panel rounded-lg p-5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-signal-amber" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-signal-amber">
                  Potential data conflict
                </span>
                <StatusBadge status={c.status} />
                <span className="text-[10px] uppercase tracking-wider text-ore-500">{c.conflict_type}</span>
                <span className="text-[10px] uppercase tracking-wider text-ore-500">{c.severity}</span>
              </div>
              <h3 className="font-mono text-sm text-copper-300">{c.field_name}</h3>
              <p className="mt-1 text-xs text-ore-500">
                Mine: {c.entity_name ?? '—'} · Period: {c.period ?? '—'}
              </p>
              <p className="mt-2 text-sm text-ore-200">{c.description}</p>

              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {c.evidence.map((e) => (
                  <div key={e.id} className="panel-inset rounded-md p-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-ore-500">
                      Source {e.label ?? ''}
                      {e.is_calculated ? ' · calculated' : ''}
                    </p>
                    <p className="mt-1 text-sm font-medium text-ore-100">
                      {e.document_name ?? e.document_id}
                      {e.document_version ? ` v${e.document_version}` : ''}
                    </p>
                    <p className="text-xs text-ore-500">
                      {e.sheet_name
                        ? `Sheet: ${e.sheet_name}`
                        : e.page_number != null
                          ? `Page ${e.page_number}`
                          : 'Source n/a'}
                    </p>
                    <p className="mt-2 text-sm text-copper-300">
                      {e.value ?? '—'}
                      {e.unit ? ` ${e.unit}` : ''}
                    </p>
                    {e.evidence_text ? (
                      <p className="mt-2 text-xs leading-relaxed text-ore-400">&ldquo;{e.evidence_text}&rdquo;</p>
                    ) : null}
                    {e.document_id ? (
                      <Link
                        to={`/documents/${e.document_id}`}
                        className="mt-2 inline-block text-[10px] font-semibold uppercase tracking-wide text-copper-400"
                      >
                        View source
                      </Link>
                    ) : null}
                  </div>
                ))}
              </div>

              {c.status === 'resolved' ? (
                <p className="mt-3 text-sm text-signal-green">
                  Resolved value: {c.selected_value}
                  {c.selected_unit ? ` ${c.selected_unit}` : ''} — {c.resolution_reason}
                </p>
              ) : null}

              {['review_required', 'detected', 'confirmed'].includes(c.status) ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onConfirm(c.id)}
                    className="inline-flex items-center gap-1.5 rounded-md bg-ore-800 px-3 py-1.5 text-xs font-semibold text-ore-100 ring-1 ring-ore-600"
                  >
                    <Check className="h-3.5 w-3.5" /> Confirm conflict
                  </button>
                  <button
                    type="button"
                    onClick={() => onDismiss(c.id)}
                    className="inline-flex items-center gap-1.5 rounded-md bg-ore-800 px-3 py-1.5 text-xs font-semibold text-ore-100 ring-1 ring-ore-600"
                  >
                    <X className="h-3.5 w-3.5" /> Dismiss
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setResolving(c.id)
                      setSelectedValue(c.evidence[0]?.value ?? '')
                      setSelectedUnit(c.evidence[0]?.unit ?? '')
                    }}
                    className="inline-flex items-center gap-1.5 rounded-md bg-copper-500/20 px-3 py-1.5 text-xs font-semibold text-copper-300 ring-1 ring-copper-500/40"
                  >
                    <Pencil className="h-3.5 w-3.5" /> Resolve
                  </button>
                </div>
              ) : null}

              {resolving === c.id ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <input
                    value={selectedValue}
                    onChange={(e) => setSelectedValue(e.target.value)}
                    placeholder="Selected verified value"
                    className="panel-inset rounded-md px-3 py-2 text-sm text-ore-100"
                  />
                  <input
                    value={selectedUnit}
                    onChange={(e) => setSelectedUnit(e.target.value)}
                    placeholder="Unit"
                    className="panel-inset rounded-md px-3 py-2 text-sm text-ore-100"
                  />
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Reason"
                    className="panel-inset rounded-md px-3 py-2 text-sm text-ore-100"
                  />
                  <button
                    type="button"
                    onClick={() => onResolve(c.id)}
                    className="rounded-md bg-copper-500 px-3 py-2 text-sm font-semibold text-ore-950"
                  >
                    Save resolution
                  </button>
                </div>
              ) : null}
            </article>
          ))
        )}
      </div>
    </div>
  )
}
