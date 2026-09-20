import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search } from 'lucide-react'
import { ApiError, documentFileUrl, semanticSearch } from '../lib/api'
import { PageHeader } from '../components/ui'

type SearchHit = {
  text: string
  score: number
  document?: string | null
  document_id: string
  page?: number | null
  sheet_name?: string | null
  source_location?: string | null
  content_type: string
  chunk_id: string
  has_conflict?: boolean
  conflict_ids?: string[]
}

export function SearchPage() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [empty, setEmpty] = useState('')
  const [results, setResults] = useState<SearchHit[]>([])
  const [searched, setSearched] = useState(false)

  async function runSearch(e?: React.FormEvent) {
    e?.preventDefault()
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError('')
    setEmpty('')
    setSearched(true)
    try {
      const res = await semanticSearch(q, 8)
      setResults(res.results)
      if (!res.results.length) {
        setEmpty('No relevant chunks above the similarity threshold. Index documents first.')
      }
    } catch (err) {
      setResults([])
      setError(err instanceof ApiError ? err.message : 'Unable to search. Check the backend connection.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Semantic Search"
        subtitle="Natural-language retrieval over indexed document chunks and structured evidence. Results come from the vector index — never fabricated."
      />

      <form onSubmit={runSearch} className="panel mx-auto max-w-3xl rounded-lg p-6 animate-fade-up">
        <label className="block text-xs uppercase tracking-[0.14em] text-ore-500">Query</label>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about production, entities, or report content…"
            className="panel-inset flex-1 rounded-md px-3 py-2.5 text-sm text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-copper-500 px-5 py-2.5 text-sm font-semibold text-ore-950 hover:bg-copper-400 disabled:opacity-40"
          >
            <Search className="h-4 w-4" />
            {loading ? 'Searching…' : 'Search'}
          </button>
        </div>
        {error ? <p className="mt-3 text-sm text-signal-red">{error}</p> : null}
        {empty ? <p className="mt-3 text-sm text-signal-amber">{empty}</p> : null}
      </form>

      <div className="mx-auto mt-6 max-w-3xl space-y-4">
        {loading ? <p className="text-sm text-ore-400">Searching indexed evidence…</p> : null}
        {!loading && searched && !results.length && !error ? (
          <p className="text-sm text-ore-500">No results for this query.</p>
        ) : null}
        {results.map((r) => (
          <article key={r.chunk_id || r.document_id + r.text.slice(0, 24)} className="panel rounded-lg p-5 animate-fade-up">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-medium text-ore-100">{r.document ?? r.document_id}</h3>
                <p className="mt-1 text-xs text-ore-500">
                  {r.sheet_name
                    ? `Sheet: ${r.sheet_name}`
                    : r.page != null
                      ? `Page ${r.page}`
                      : 'Source n/a'}
                  {r.source_location ? ` · ${r.source_location}` : ''}
                  {' · '}
                  {r.content_type.replace(/_/g, ' ')}
                </p>
              </div>
              <p className="text-sm tabular-nums text-copper-300">
                Relevance: {Math.round(r.score * 100)}%
              </p>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-ore-200">&ldquo;{r.text}&rdquo;</p>
            {r.has_conflict ? (
              <p className="mt-2 text-xs text-signal-amber">
                This evidence participates in a validation conflict.{' '}
                <Link to="/validation" className="font-semibold text-copper-400 hover:text-copper-300">
                  Open validation
                </Link>
              </p>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-3 text-xs font-semibold uppercase tracking-wide">
              <Link to={`/documents/${r.document_id}${r.page != null ? `#page-${r.page}` : ''}`} className="text-copper-400 hover:text-copper-300">
                Open in app
              </Link>
              <a
                href={documentFileUrl(r.document_id, r.page)}
                target="_blank"
                rel="noreferrer"
                className="text-ore-300 hover:text-ore-100"
              >
                View original file
              </a>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
