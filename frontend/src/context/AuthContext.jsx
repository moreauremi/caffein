// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../lib/api'

// Utilisateur connecté + état de l'instance (installation à faire, mode démo).
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [state, setState] = useState({ loading: true, user: null, needsSetup: false, demo: false })

  const refresh = useCallback(async () => {
    const status = await api.get('/api/setup/status').catch(() => ({ needs_setup: false, demo: false }))
    let user = null
    if (!status.needs_setup) user = await api.get('/api/auth/me').catch(() => null)
    setState({ loading: false, user, needsSetup: status.needs_setup, demo: status.demo })
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.resolve().then(() => !cancelled && refresh())
    const onUnauthorized = () => setState((s) => ({ ...s, user: null }))
    window.addEventListener('caffein:unauthorized', onUnauthorized)
    return () => {
      cancelled = true
      window.removeEventListener('caffein:unauthorized', onUnauthorized)
    }
  }, [refresh])

  const signIn = useCallback(async (email, password) => {
    const { user } = await api.post('/api/auth/login', { email, password })
    setState((s) => ({ ...s, user, needsSetup: false }))
    return user
  }, [])

  const signInDemo = useCallback(async () => {
    const { user } = await api.post('/api/auth/demo')
    setState((s) => ({ ...s, user }))
    return user
  }, [])

  const completeSetup = useCallback(async (payload) => {
    const { user } = await api.post('/api/setup', payload)
    setState((s) => ({ ...s, user, needsSetup: false }))
    return user
  }, [])

  const signOut = useCallback(async () => {
    await api.post('/api/auth/logout').catch(() => {})
    setState((s) => ({ ...s, user: null }))
  }, [])

  const setUser = useCallback((user) => setState((s) => ({ ...s, user })), [])

  return (
    <AuthContext.Provider value={{ ...state, refresh, signIn, signInDemo, completeSetup, signOut, setUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
