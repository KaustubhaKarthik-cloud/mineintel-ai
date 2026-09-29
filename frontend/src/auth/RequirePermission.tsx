import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

/** Frontend gate — backend authorization remains authoritative. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string
  children: React.ReactNode
}) {
  const { loading, hasPermission } = useAuth()
  if (loading) return <p className="p-6 text-ore-400">Checking access…</p>
  if (!hasPermission(permission)) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}
