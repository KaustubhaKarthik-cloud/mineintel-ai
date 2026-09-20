import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Eye,
  EyeOff,
  Loader2,
  Mountain,
  Shield,
  ClipboardCheck,
  BarChart3,
  ArrowRight,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'

type DemoRole = {
  id: string
  username: string
  password: string
  label: string
  blurb: string
  icon: typeof Shield
}

const DEMO_ROLES: DemoRole[] = [
  {
    id: 'admin',
    username: 'admin',
    password: 'admin123',
    label: 'Admin',
    blurb: 'Users · audit · full control',
    icon: Shield,
  },
  {
    id: 'analyst',
    username: 'analyst',
    password: 'analyst123',
    label: 'Analyst',
    blurb: 'Search · analytics · reports',
    icon: BarChart3,
  },
  {
    id: 'reviewer',
    username: 'reviewer',
    password: 'reviewer123',
    label: 'Reviewer',
    blurb: 'Review · validate · evidence',
    icon: ClipboardCheck,
  },
]

export function LoginPage() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [selectedRole, setSelectedRole] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [shake, setShake] = useState(false)

  const canSubmit = useMemo(
    () => username.trim().length > 0 && password.length > 0 && !busy,
    [username, password, busy],
  )

  function pickRole(role: DemoRole) {
    setSelectedRole(role.id)
    setUsername(role.username)
    setPassword(role.password)
    setError('')
    setShowPassword(false)
  }

  async function signIn(userName: string, pass: string) {
    setBusy(true)
    setError('')
    try {
      await login(userName.trim(), pass)
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
      setShake(true)
      window.setTimeout(() => setShake(false), 450)
    } finally {
      setBusy(false)
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    await signIn(username, password)
  }

  async function quickSignIn(role: DemoRole) {
    pickRole(role)
    await signIn(role.username, role.password)
  }

  if (user && !user.anonymous) {
    return (
      <div className="mine-grid-bg flex min-h-screen items-center justify-center px-4">
        <div className="panel w-full max-w-md rounded-xl p-8 animate-fade-up ring-1 ring-copper-500/20">
          <BrandHeader />
          <p className="mt-6 text-sm text-ore-300">
            Signed in as <span className="font-medium text-copper-300">{user.display_name || user.username}</span>
            <span className="text-ore-500"> · {user.role}</span>
          </p>
          <Link
            to="/"
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-md bg-copper-500 px-4 py-3 text-sm font-semibold text-ore-950 transition hover:bg-copper-400"
          >
            Continue to dashboard <ArrowRight className="h-4 w-4" />
          </Link>
          <button
            type="button"
            className="mt-3 w-full text-center text-xs text-ore-500 hover:text-ore-300"
            onClick={() => {
              setUsername('')
              setPassword('')
              setSelectedRole(null)
            }}
          >
            Switch account
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mine-grid-bg relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-10">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            'radial-gradient(ellipse 50% 40% at 50% 20%, rgba(200,132,58,0.18), transparent 70%)',
        }}
      />

      <div
        className={[
          'panel relative w-full max-w-lg rounded-xl p-7 shadow-[0_24px_80px_rgba(0,0,0,0.45)] ring-1 ring-ore-700/60 animate-fade-up sm:p-9',
          shake ? 'login-shake' : '',
        ].join(' ')}
      >
        <BrandHeader />
        <p className="mt-4 text-sm leading-relaxed text-ore-400">
          Pick a demo role to fill credentials, or type your own. Passwords stay in the form — click a
          card to load them.
        </p>

        <div className="mt-6 grid gap-2.5 sm:grid-cols-3">
          {DEMO_ROLES.map((role) => {
            const Icon = role.icon
            const active = selectedRole === role.id
            return (
              <button
                key={role.id}
                type="button"
                disabled={busy}
                onClick={() => pickRole(role)}
                onDoubleClick={() => void quickSignIn(role)}
                className={[
                  'group rounded-lg px-3 py-3 text-left transition duration-200',
                  'ring-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-copper-400',
                  active
                    ? 'bg-copper-500/15 ring-copper-500/50 shadow-[inset_0_0_0_1px_rgba(200,132,58,0.25)]'
                    : 'bg-ore-950/50 ring-ore-700/70 hover:bg-ore-850 hover:ring-ore-600',
                  busy ? 'opacity-60' : '',
                ].join(' ')}
              >
                <Icon
                  className={[
                    'mb-2 h-4 w-4 transition',
                    active ? 'text-copper-300' : 'text-ore-500 group-hover:text-copper-400',
                  ].join(' ')}
                />
                <p
                  className={[
                    'text-sm font-semibold',
                    active ? 'text-copper-200' : 'text-ore-100',
                  ].join(' ')}
                >
                  {role.label}
                </p>
                <p className="mt-0.5 text-[11px] leading-snug text-ore-500">{role.blurb}</p>
                {active ? (
                  <p className="mt-2 text-[10px] uppercase tracking-[0.14em] text-copper-400">
                    Loaded · double-click to sign in
                  </p>
                ) : null}
              </button>
            )
          })}
        </div>

        <form onSubmit={onSubmit} className="mt-7 space-y-4">
          <label className="block">
            <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-ore-500">
              Username
            </span>
            <input
              className="mt-1.5 w-full rounded-md border border-ore-700 bg-ore-950/80 px-3.5 py-2.5 text-sm text-ore-100 outline-none transition placeholder:text-ore-600 focus:border-copper-500/60 focus:ring-2 focus:ring-copper-500/25"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value)
                setSelectedRole(null)
              }}
              autoComplete="username"
              placeholder="Select a role or type a username"
              required
            />
          </label>

          <label className="block">
            <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-ore-500">
              Password
            </span>
            <div className="relative mt-1.5">
              <input
                type={showPassword ? 'text' : 'password'}
                className="w-full rounded-md border border-ore-700 bg-ore-950/80 px-3.5 py-2.5 pr-11 text-sm text-ore-100 outline-none transition placeholder:text-ore-600 focus:border-copper-500/60 focus:ring-2 focus:ring-copper-500/25"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setSelectedRole(null)
                }}
                autoComplete="current-password"
                placeholder="••••••••"
                required
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-ore-500 transition hover:bg-ore-800 hover:text-ore-200"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </label>

          {error ? (
            <p className="rounded-md border border-signal-red/30 bg-signal-red/10 px-3 py-2 text-sm text-signal-red">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={!canSubmit}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-copper-500 px-4 py-3 text-sm font-semibold text-ore-950 transition hover:bg-copper-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Signing in…
              </>
            ) : (
              <>
                Sign in {selectedRole ? `as ${selectedRole}` : null}
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </form>

        <div className="mt-6 flex flex-col items-center gap-2 border-t border-ore-800/80 pt-5">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm text-ore-400 transition hover:text-copper-300"
          >
            Continue without signing in
            <span className="text-ore-600">·</span>
            <span className="text-ore-500">demo analyst access</span>
          </Link>
          <p className="text-[11px] text-ore-600">SIH26023 · local JWT auth · bcrypt passwords</p>
        </div>
      </div>
    </div>
  )
}

function BrandHeader() {
  return (
    <div className="flex items-center gap-3.5">
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-ore-850 ring-1 ring-copper-500/45 shadow-[0_0_24px_rgba(200,132,58,0.12)]">
        <Mountain className="h-6 w-6 text-copper-400" strokeWidth={2.25} />
      </div>
      <div>
        <p className="font-display text-2xl leading-none tracking-[0.08em] text-ore-100">MINEINTEL</p>
        <p className="mt-1 text-[10px] font-medium uppercase tracking-[0.28em] text-copper-400">
          Mining intelligence · sign in
        </p>
      </div>
    </div>
  )
}
