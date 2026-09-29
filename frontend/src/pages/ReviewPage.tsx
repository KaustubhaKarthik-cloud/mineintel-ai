import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, X, Pencil } from 'lucide-react'
import { getReviews, submitReviewAction } from '../lib/api'
import type { ReviewItem } from '../types'
import { ConfidenceBar, PageHeader, StatusBadge } from '../components/ui'

export function ReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [pending, setPending] = useState(0)
  const [editing, setEditing] = useState<string | null>(null)
  const [correctValue, setCorrectValue] = useState('')
  const [correctUnit, setCorrectUnit] = useState('')
  const [reason, setReason] = useState('')

  function reload() {
    return getReviews().then((r) => {
      setItems(r.items)
      setPending(r.pending)
    })
  }

  useEffect(() => {
    reload()
  }, [])

  async function act(
    id: string,
    action: 'approve' | 'reject' | 'correct',
    value?: string,
  ) {
    const updated = await submitReviewAction(id, action, value, {
      corrected_unit: correctUnit || undefined,
      review_notes: reason || undefined,
    })
    if (updated) {
      setItems((prev) => prev.map((item) => (item.id === id ? updated : item)))
      setPending((p) => Math.max(0, p - (updated.status === 'pending' ? 0 : 1)))
    } else {
      await reload()
    }
    setEditing(null)
    setReason('')
    setCorrectUnit('')
  }

  return (
    <div>
      <PageHeader
        title="Review Queue"
        subtitle="Human-in-the-loop validation for low-confidence AI extractions. Original AI values are preserved on correction."
        action={
          <div className="panel rounded-md px-4 py-2 text-sm">
            <span className="text-ore-400">Backlog </span>
            <span className="font-display text-2xl text-signal-amber">{pending}</span>
          </div>
        }
      />

      <div className="space-y-3 animate-fade-up">
        {items.map((item) => (
          <div key={item.id} className="panel rounded-lg p-5">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-signal-amber">
              {item.status === 'pending' ? 'Review required' : item.status}
            </div>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-mono text-sm text-copper-300">{item.field_name}</h3>
                  <StatusBadge status={item.status} />
                  {item.priority >= 3 ? (
                    <span className="text-[10px] uppercase tracking-wider text-signal-red">High priority</span>
                  ) : null}
                </div>
                <p className="mt-1 text-xs text-ore-500">
                  Mine: {item.entity_name ?? item.mine_name ?? '—'}
                  {item.financial_year ? ` · Year: ${item.financial_year}` : ''}
                </p>
                <p className="mt-1 text-xs text-ore-500">
                  Source: {item.source_document ?? item.document_name ?? '—'}
                  {item.sheet_name
                    ? ` · Sheet: ${item.sheet_name}`
                    : item.page_number != null
                      ? ` · Page: ${item.page_number}`
                      : ''}
                  {item.geological_fact_id
                    ? ` · Fact: ${item.geological_fact_id.slice(0, 8)}…`
                    : item.extracted_fact_id
                      ? ` · Fact: ${item.extracted_fact_id.slice(0, 8)}…`
                      : ''}
                </p>
              </div>
              <ConfidenceBar value={item.confidence} />
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="panel-inset rounded-md px-3 py-2.5">
                <p className="text-[10px] uppercase tracking-[0.14em] text-ore-500">AI value</p>
                <p className="mt-1 font-medium text-ore-100">
                  {item.extracted_value ?? '—'}
                  {item.original_unit ? ` ${item.original_unit}` : ''}
                </p>
              </div>
              <div className="panel-inset rounded-md px-3 py-2.5">
                <p className="text-[10px] uppercase tracking-[0.14em] text-ore-500">Corrected / verified</p>
                <p className="mt-1 font-medium text-ore-100">
                  {item.corrected_value ?? '—'}
                  {item.corrected_unit ? ` ${item.corrected_unit}` : ''}
                </p>
              </div>
            </div>

            {item.evidence_text ? (
              <div className="panel-inset mt-3 rounded-md px-3 py-2.5">
                <p className="text-[10px] uppercase tracking-[0.14em] text-ore-500">Evidence</p>
                <p className="mt-1 text-sm text-ore-300">&ldquo;{item.evidence_text}&rdquo;</p>
              </div>
            ) : null}

            <div className="mt-3">
              <Link
                to={`/documents/${item.document_id}`}
                className="text-xs font-medium text-copper-400 hover:text-copper-300"
              >
                Open document →
              </Link>
            </div>

            {item.status === 'pending' ? (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => act(item.id, 'approve')}
                  className="inline-flex items-center gap-1.5 rounded-md bg-signal-green/15 px-3 py-1.5 text-xs font-semibold text-signal-green ring-1 ring-signal-green/30 hover:bg-signal-green/25"
                >
                  <Check className="h-3.5 w-3.5" /> Approve
                </button>
                <button
                  type="button"
                  onClick={() => act(item.id, 'reject')}
                  className="inline-flex items-center gap-1.5 rounded-md bg-signal-red/15 px-3 py-1.5 text-xs font-semibold text-signal-red ring-1 ring-signal-red/30 hover:bg-signal-red/25"
                >
                  <X className="h-3.5 w-3.5" /> Reject
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(item.id)
                    setCorrectValue(item.extracted_value ?? '')
                    setCorrectUnit(item.original_unit ?? '')
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-ore-800 px-3 py-1.5 text-xs font-semibold text-ore-200 ring-1 ring-ore-600 hover:bg-ore-700"
                >
                  <Pencil className="h-3.5 w-3.5" /> Correct
                </button>
                {editing === item.id ? (
                  <div className="mt-2 flex w-full flex-wrap items-end gap-2">
                    <label className="text-xs text-ore-400">
                      Corrected value
                      <input
                        value={correctValue}
                        onChange={(e) => setCorrectValue(e.target.value)}
                        className="panel-inset mt-1 block rounded-md px-3 py-1.5 text-sm text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
                      />
                    </label>
                    <label className="text-xs text-ore-400">
                      Unit
                      <input
                        value={correctUnit}
                        onChange={(e) => setCorrectUnit(e.target.value)}
                        className="panel-inset mt-1 block w-24 rounded-md px-3 py-1.5 text-sm text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
                      />
                    </label>
                    <label className="min-w-[200px] flex-1 text-xs text-ore-400">
                      Reason
                      <input
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        className="panel-inset mt-1 block w-full rounded-md px-3 py-1.5 text-sm text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => act(item.id, 'correct', correctValue)}
                      className="rounded-md bg-copper-500 px-3 py-1.5 text-xs font-semibold text-ore-950"
                    >
                      Save correction
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}
