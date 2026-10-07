// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

// Charge une ressource de l'API. Pendant le chargement d'un nouveau chemin, les données
// précédentes restent affichées (pas de clignotement en changeant de filtre).
export function useApi(path) {
  const [state, setState] = useState({ path: null, data: null, error: null })

  const fetchPath = useCallback(() => {
    if (!path) return Promise.resolve()
    return api.get(path)
      .then((data) => setState({ path, data, error: null }))
      .catch((error) => setState((s) => ({ ...s, path, error })))
  }, [path])

  useEffect(() => {
    if (!path) return undefined
    let cancelled = false
    api.get(path)
      .then((data) => !cancelled && setState({ path, data, error: null }))
      .catch((error) => !cancelled && setState((s) => ({ ...s, path, error })))
    return () => { cancelled = true }
  }, [path])

  const setData = useCallback((next) => setState((s) => ({ ...s, data: typeof next === 'function' ? next(s.data) : next })), [])

  return {
    data: state.data,
    error: state.path === path ? state.error : null,
    loading: Boolean(path) && state.path !== path,
    reload: fetchPath,
    setData,
  }
}
