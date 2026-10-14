// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { LEVELS, pagePath } from '../lib/meta'

// Description de l'espace de l'utilisateur, fournie par le serveur (/api/meta) : modules visibles, pages,
// entités et niveaux de droits. La navigation et les écrans génériques en découlent ; le serveur reste seul
// juge des droits (l'interface ne fait que masquer ce qui est interdit).
const MetaContext = createContext(null)

export function MetaProvider({ children }) {
  const [state, setState] = useState({ meta: null, error: null })

  const reload = useCallback(() => api.get('/api/meta')
    .then((meta) => setState({ meta, error: null }))
    .catch((error) => setState((s) => ({ ...s, error }))), [])

  useEffect(() => {
    let cancelled = false
    api.get('/api/meta')
      .then((meta) => !cancelled && setState({ meta, error: null }))
      .catch((error) => !cancelled && setState((s) => ({ ...s, error })))
    return () => { cancelled = true }
  }, [])

  const value = useMemo(() => {
    const meta = state.meta
    const modules = meta?.modules || []
    const bySlug = Object.fromEntries(modules.map((m) => [m.slug, m]))
    const byKey = Object.fromEntries(modules.map((m) => [m.key, m]))
    // Page qui affiche une entité (lien depuis une référence, un chiffre clé…)
    const entityPages = {}
    for (const module of modules) {
      for (const page of module.pages) {
        if (page.entity && !entityPages[page.entity]) entityPages[page.entity] = pagePath(module, page)
      }
    }
    return {
      meta, error: state.error, loading: !meta && !state.error, reload,
      modules, isAdmin: Boolean(meta?.is_admin),
      moduleBySlug: (slug) => bySlug[slug] || null,
      moduleByKey: (key) => byKey[key] || null,
      entity: (key) => meta?.entities?.[key] || null,
      entityPath: (key) => entityPages[key] || null,
      level: (key) => meta?.levels?.[key] ?? 0,
      can: (key, level = 'read') => (meta?.levels?.[key] ?? 0) >= (LEVELS[level] ?? level),
    }
  }, [state, reload])

  return <MetaContext.Provider value={value}>{children}</MetaContext.Provider>
}

export const useMeta = () => useContext(MetaContext)
