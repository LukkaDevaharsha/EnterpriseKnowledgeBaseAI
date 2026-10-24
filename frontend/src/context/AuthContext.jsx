import { useCallback, useEffect, useMemo, useState } from 'react'
import { authApi } from '../api/client'
import { AuthContext } from './auth'

const TOKEN_KEY = 'ekb_access_token'

export default function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem(TOKEN_KEY)))

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    setLoading(false)
  }, [])

  useEffect(() => {
    window.addEventListener('auth:expired', logout)
    return () => window.removeEventListener('auth:expired', logout)
  }, [logout])

  useEffect(() => {
    let active = true
    if (!token) return () => { active = false }
    authApi.me(token).then((data) => {
      if (active) setUser(data.user)
    }).catch(() => {
      if (active) logout()
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [token, logout])

  const login = useCallback(async (credentials) => {
    const data = await authApi.login(credentials)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    setUser(data.user)
    setLoading(false)
    return data.user
  }, [])

  const register = useCallback((details) => authApi.register(details), [])
  const value = useMemo(() => ({ token, user, loading, login, register, logout }), [token, user, loading, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
