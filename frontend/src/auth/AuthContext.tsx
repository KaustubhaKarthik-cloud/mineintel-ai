import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { type AuthUserInfo, getMe, login as apiLogin, logout as apiLogout } from '../lib/api'

type AuthContextValue = {
  user: AuthUserInfo | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  hasPermission: (perm: string) => boolean
  isAdmin: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUserInfo | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const me = await getMe()
      setUser(me)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Always resolve current user (anonymous demo analyst when no token)
    void refresh()
  }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    const data = await apiLogin(username, password)
    setUser(data.user)
  }, [])

  const logout = useCallback(async () => {
    await apiLogout()
    setLoading(true)
    await refresh()
  }, [refresh])

  const value = useMemo<AuthContextValue>(() => {
    const perms = new Set(user?.permissions || [])
    return {
      user,
      loading,
      login,
      logout,
      refresh,
      hasPermission: (perm: string) => perms.has(perm),
      isAdmin: user?.role === 'admin',
    }
  }, [user, loading, login, logout, refresh])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
