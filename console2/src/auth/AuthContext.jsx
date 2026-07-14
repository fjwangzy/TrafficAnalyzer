import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { clearAccessToken, getAccessToken, platformApi, setAccessToken, UNAUTHORIZED_EVENT } from '../lib/api'

const AuthContext = createContext(null)

const ROLE_MAP = {
  admin: 'admin',
  operator: 'commander',
  viewer: 'analyst',
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState(getAccessToken() ? 'checking' : 'anonymous')

  const logout = useCallback(() => {
    clearAccessToken()
    setUser(null)
    setStatus('anonymous')
  }, [])

  useEffect(() => {
    const handleUnauthorized = () => logout()
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [logout])

  useEffect(() => {
    if (!getAccessToken()) return
    let active = true
    platformApi.currentUser()
      .then((nextUser) => {
        if (!active) return
        setUser(nextUser)
        setStatus('authenticated')
      })
      .catch(() => {
        if (active) logout()
      })
    return () => { active = false }
  }, [logout])

  const login = useCallback(async (username, password) => {
    const response = await platformApi.login(username, password)
    setAccessToken(response.access_token)
    setUser(response.user)
    setStatus('authenticated')
    return response.user
  }, [])

  const value = useMemo(() => ({
    user,
    status,
    login,
    logout,
    isAuthenticated: status === 'authenticated',
    platformRole: user?.role || null,
    consoleRole: ROLE_MAP[user?.role] || 'analyst',
  }), [user, status, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

export function isSafeRedirect(value) {
  if (!value || typeof value !== 'string') return false
  return value.startsWith('/') && !value.startsWith('//') && !value.includes('://')
}
