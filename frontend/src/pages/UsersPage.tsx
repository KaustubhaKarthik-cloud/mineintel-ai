import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { ApiError, createUser, formatDate, listUsers, updateUser } from '../lib/api'
import { PageHeader, StatusBadge } from '../components/ui'

type UserRow = {
  id: string
  username: string
  display_name?: string | null
  role: string
  status: string
  created_at?: string | null
}

export function UsersPage() {
  const { isAdmin, hasPermission, user } = useAuth()
  const canManageUsers = isAdmin || Boolean(user?.permissions?.includes('users.manage'))
  const [items, setItems] = useState<UserRow[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('user')
  const [busy, setBusy] = useState(false)

  async function reload() {
    setLoading(true)
    setError('')
    try {
      const res = await listUsers()
      setItems(res.items)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Unable to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (canManageUsers) void reload()
    else setLoading(false)
  }, [canManageUsers])

  if (!isAdmin && !hasPermission('users.manage')) {
    return (
      <div>
        <PageHeader title="Users" subtitle="Admin only" />
        <p className="text-signal-amber">Sign in as an admin to manage users.</p>
      </div>
    )
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await createUser({
        username,
        password,
        display_name: displayName || undefined,
        role,
      })
      setUsername('')
      setPassword('')
      setDisplayName('')
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  async function setRoleFor(id: string, next: string) {
    try {
      await updateUser(id, { role: next })
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Role update failed')
    }
  }

  async function setStatusFor(id: string, next: string) {
    try {
      await updateUser(id, { status: next })
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Status update failed')
    }
  }

  return (
    <div>
      <PageHeader
        title="User management"
        subtitle="Create users, change roles, and enable or disable accounts. Passwords are never shown."
      />

      {error ? <p className="mb-4 text-sm text-signal-red">{error}</p> : null}

      <section className="panel mb-6 rounded-lg p-5">
        <h2 className="mb-3 text-sm uppercase tracking-wide text-copper-400">Create user</h2>
        <form onSubmit={onCreate} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <input
            className="rounded-md border border-ore-700 bg-ore-950 px-3 py-2 text-sm"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <input
            className="rounded-md border border-ore-700 bg-ore-950 px-3 py-2 text-sm"
            placeholder="Display name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <input
            type="password"
            className="rounded-md border border-ore-700 bg-ore-950 px-3 py-2 text-sm"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
          <select
            className="rounded-md border border-ore-700 bg-ore-950 px-3 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="admin">admin</option>
            <option value="user">user</option>
          </select>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-copper-500/90 px-3 py-2 text-sm font-medium text-ore-950 disabled:opacity-50"
          >
            Create
          </button>
        </form>
      </section>

      {loading ? (
        <p className="text-ore-400">Loading users…</p>
      ) : (
        <div className="panel overflow-x-auto rounded-lg">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-ore-700/60 text-xs uppercase tracking-wide text-ore-500">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id} className="border-b border-ore-800/50">
                  <td className="px-4 py-3">
                    <p className="font-medium text-ore-100">{u.display_name || u.username}</p>
                    <p className="text-xs text-ore-500">{u.username}</p>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className="rounded border border-ore-700 bg-ore-950 px-2 py-1 text-xs"
                      value={u.role === 'analyst' ? 'user' : u.role === 'reviewer' ? 'admin' : u.role}
                      onChange={(e) => setRoleFor(u.id, e.target.value)}
                    >
                      <option value="admin">admin</option>
                      <option value="user">user</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={u.status} />
                  </td>
                  <td className="px-4 py-3 text-ore-400">{formatDate(u.created_at)}</td>
                  <td className="px-4 py-3">
                    {u.status === 'active' ? (
                      <button
                        type="button"
                        className="text-xs text-signal-amber hover:underline"
                        onClick={() => setStatusFor(u.id, 'disabled')}
                      >
                        Disable
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="text-xs text-signal-green hover:underline"
                        onClick={() => setStatusFor(u.id, 'active')}
                      >
                        Enable
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
