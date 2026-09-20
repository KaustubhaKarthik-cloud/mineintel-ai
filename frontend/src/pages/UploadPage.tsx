import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { UploadCloud, FileUp, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'
import { ApiError, formatBytes, stageLabel, uploadDocument } from '../lib/api'
import type { DocumentDetail } from '../types'
import { PageHeader, StatusBadge } from '../components/ui'

type UiPhase = 'idle' | 'uploading' | 'processing' | 'done' | 'error'

const ALLOWED = ['.pdf', '.xlsx', '.xls', '.png', '.jpg', '.jpeg']

function extOf(name: string) {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [mineName, setMineName] = useState('')
  const [category, setCategory] = useState('Production Report')
  const [dragging, setDragging] = useState(false)
  const [phase, setPhase] = useState<UiPhase>('idle')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<DocumentDetail | null>(null)

  const pickFile = useCallback((f: File | null) => {
    if (!f) return
    const ext = extOf(f.name)
    if (!ALLOWED.includes(ext)) {
      setPhase('error')
      setMessage(`Unsupported type ${ext || '(none)'}. Allowed: PDF, Excel, PNG, JPG.`)
      setFile(null)
      return
    }
    setFile(f)
    setPhase('idle')
    setMessage('')
    setResult(null)
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      pickFile(e.dataTransfer.files?.[0] ?? null)
    },
    [pickFile],
  )

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!file) return
    setPhase('uploading')
    setMessage('Uploading…')
    setResult(null)
    try {
      // Brief UI beat then switch to processing while request runs (sync pipeline)
      setTimeout(() => {
        setPhase((p) => (p === 'uploading' ? 'processing' : p))
        setMessage('Processing… extracting text / OCR if required…')
      }, 200)

      const doc = await uploadDocument(file, mineName, category)
      setResult(doc)
      if (doc.status === 'failed') {
        setPhase('error')
        setMessage(doc.error_message || 'Processing failed')
      } else {
        setPhase('done')
        setMessage(stageLabel(doc.processing_stage) || 'Processing complete')
      }
      setFile(null)
    } catch (err) {
      setPhase('error')
      setMessage(err instanceof ApiError ? err.message : 'Upload failed. Is the backend running?')
    }
  }

  return (
    <div>
      <PageHeader
        title="Upload Mining Documents"
        subtitle="Digital PDF, scanned PDF, Excel, or images. Originals are stored untouched under documents/original/."
      />

      <form onSubmit={handleSubmit} className="mx-auto max-w-3xl animate-fade-up">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={[
            'panel relative flex flex-col items-center justify-center rounded-lg border-dashed px-6 py-16 transition',
            dragging ? 'border-copper-400 bg-copper-500/10' : 'border-ore-600',
          ].join(' ')}
        >
          <UploadCloud className="h-12 w-12 text-copper-400" strokeWidth={1.5} />
          <p className="mt-4 font-display text-2xl uppercase tracking-wide text-ore-100">
            Upload Mining Documents
          </p>
          <p className="mt-2 text-sm text-ore-400">Supported: PDF, Excel, PNG, JPG · max 50 MB</p>
          <label className="mt-6 cursor-pointer rounded-md bg-ore-800 px-4 py-2 text-sm font-medium text-ore-100 ring-1 ring-ore-600 transition hover:bg-ore-700">
            <span className="inline-flex items-center gap-2">
              <FileUp className="h-4 w-4" /> Browse files
            </span>
            <input
              type="file"
              className="hidden"
              accept=".pdf,.xlsx,.xls,.jpg,.jpeg,.png"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>

        {file ? (
          <div className="panel mt-4 rounded-lg px-4 py-3 text-sm">
            <p className="font-medium text-ore-100">{file.name}</p>
            <p className="mt-1 text-xs text-ore-400">
              Type: {extOf(file.name).replace('.', '').toUpperCase()} · Size: {formatBytes(file.size)}
            </p>
          </div>
        ) : null}

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1.5 block text-xs uppercase tracking-[0.14em] text-ore-400">Mine name</span>
            <input
              value={mineName}
              onChange={(e) => setMineName(e.target.value)}
              placeholder="e.g. Bailadila Iron Ore Mine"
              className="panel-inset w-full rounded-md px-3 py-2.5 text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block text-xs uppercase tracking-[0.14em] text-ore-400">Category</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="panel-inset w-full rounded-md px-3 py-2.5 text-ore-100 outline-none focus:ring-2 focus:ring-copper-500/40"
            >
              <option>Production Report</option>
              <option>Safety Audit</option>
              <option>Environmental</option>
              <option>Lease Document</option>
              <option>Grade Analysis</option>
              <option>Monthly Return</option>
              <option>Operations Report</option>
            </select>
          </label>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <button
            type="submit"
            disabled={!file || phase === 'uploading' || phase === 'processing'}
            className="rounded-md bg-copper-500 px-5 py-2.5 text-sm font-semibold text-ore-950 transition hover:bg-copper-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {phase === 'uploading' || phase === 'processing' ? 'Processing…' : 'Process Documents'}
          </button>

          {phase === 'uploading' || phase === 'processing' ? (
            <p className="inline-flex items-center gap-2 text-sm text-signal-blue">
              <Loader2 className="h-4 w-4 animate-spin" /> {message}
            </p>
          ) : null}
          {phase === 'done' ? (
            <p className="inline-flex items-center gap-2 text-sm text-signal-green">
              <CheckCircle2 className="h-4 w-4" /> {message}
            </p>
          ) : null}
          {phase === 'error' ? (
            <p className="inline-flex items-center gap-2 text-sm text-signal-red">
              <AlertTriangle className="h-4 w-4" /> {message}
            </p>
          ) : null}
        </div>

        {result ? (
          <div className="panel mt-6 rounded-lg p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium text-ore-100">{result.original_filename}</p>
                <p className="mt-1 text-xs text-ore-500">
                  {result.page_count} units extracted · stage: {result.processing_stage ?? '—'}
                </p>
              </div>
              <StatusBadge status={result.status} />
            </div>
            <Link
              to={`/documents/${result.id}`}
              className="mt-4 inline-block text-sm font-semibold text-copper-400 hover:text-copper-300"
            >
              View extracted content →
            </Link>
          </div>
        ) : null}

        <div className="panel mt-8 rounded-lg p-5">
          <h2 className="font-display text-lg uppercase tracking-wide text-ore-100">Phase 2 pipeline</h2>
          <ol className="mt-3 grid gap-3 text-sm text-ore-300 sm:grid-cols-2">
            <li className="panel-inset rounded-md px-3 py-2">1. File validation + type detection</li>
            <li className="panel-inset rounded-md px-3 py-2">2. Digital PDF text (PyMuPDF) or OCR</li>
            <li className="panel-inset rounded-md px-3 py-2">3. Excel sheets → structured text/tables</li>
            <li className="panel-inset rounded-md px-3 py-2">4. Page/sheet storage → ready for Phase 3</li>
          </ol>
        </div>
      </form>
    </div>
  )
}
