import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

export function AppLayout() {
  const { user, logout, loading } = useAuth()

  return (
    <div className="mine-grid-bg flex min-h-screen">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-ore-700/40 bg-ore-950/60 px-8 backdrop-blur-sm">
          <p className="text-xs uppercase tracking-[0.18em] text-ore-400">
            Smart India Hackathon Prototype
          </p>
          <div className="flex items-center gap-3 text-xs text-ore-400">
            <span className="hidden sm:inline">Verified data only · evidence grounded</span>
            {loading ? (
              <span className="rounded bg-ore-800 px-2 py-1 text-ore-500">…</span>
            ) : (
              <>
                <span className="rounded bg-ore-800 px-2 py-1 font-medium text-copper-300 ring-1 ring-ore-700">
                  {user?.display_name || user?.username || 'guest'} · {user?.role || '—'}
                </span>
                {user && !user.anonymous ? (
                  <button
                    type="button"
                    onClick={() => void logout()}
                    className="rounded bg-ore-800 px-2 py-1 text-ore-300 ring-1 ring-ore-700 hover:text-ore-100"
                  >
                    Sign out
                  </button>
                ) : (
                  <Link
                    to="/login"
                    className="rounded bg-copper-500/20 px-2 py-1 text-copper-300 ring-1 ring-copper-500/30 hover:bg-copper-500/30"
                  >
                    Sign in
                  </Link>
                )}
              </>
            )}
          </div>
        </header>
        <div className="flex-1 overflow-y-auto px-8 py-7">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
