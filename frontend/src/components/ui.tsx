import type { ReactNode } from 'react'

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: ReactNode
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4 animate-fade-up">
      <div>
        <h1 className="font-display text-3xl uppercase tracking-wide text-ore-100 sm:text-4xl">
          {title}
        </h1>
        {subtitle ? <p className="mt-1.5 max-w-2xl text-sm text-ore-400">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    indexed: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    not_indexed: 'bg-ore-700/40 text-ore-400 ring-ore-600/40',
    indexing: 'bg-signal-blue/15 text-signal-blue ring-signal-blue/30',
    index_failed: 'bg-signal-red/15 text-signal-red ring-signal-red/30',
    stale: 'bg-signal-amber/15 text-signal-amber ring-signal-amber/30',
    detected: 'bg-signal-amber/15 text-signal-amber ring-signal-amber/30',
    review_required: 'bg-signal-amber/15 text-signal-amber ring-signal-amber/30',
    confirmed: 'bg-signal-red/15 text-signal-red ring-signal-red/30',
    resolved: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    dismissed: 'bg-ore-700/40 text-ore-400 ring-ore-600/40',
    approved: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    completed: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    high_confidence: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    extracted: 'bg-copper-500/15 text-copper-400 ring-copper-500/30',
    pending_review: 'bg-signal-amber/15 text-signal-amber ring-signal-amber/30',
    pending: 'bg-signal-amber/15 text-signal-amber ring-signal-amber/30',
    processing: 'bg-signal-blue/15 text-signal-blue ring-signal-blue/30',
    uploaded: 'bg-ore-700/40 text-ore-300 ring-ore-600/40',
    failed: 'bg-signal-red/15 text-signal-red ring-signal-red/30',
    rejected: 'bg-signal-red/15 text-signal-red ring-signal-red/30',
    corrected: 'bg-signal-blue/15 text-signal-blue ring-signal-blue/30',
    ready: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    draft: 'bg-ore-700/40 text-ore-400 ring-ore-600/40',
    operational: 'bg-signal-green/15 text-signal-green ring-signal-green/30',
    demo: 'bg-copper-500/15 text-copper-400 ring-copper-500/30',
  }
  const cls = colors[status] ?? 'bg-ore-700/40 text-ore-300 ring-ore-600/40'
  return (
    <span className={`inline-flex rounded px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ring-1 ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color =
    pct >= 80 ? 'bg-signal-green' : pct >= 60 ? 'bg-signal-amber' : 'bg-signal-red'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-ore-800">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-ore-300">{pct}%</span>
    </div>
  )
}
