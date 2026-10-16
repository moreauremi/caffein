// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { pick as pickLabel, translate } from '../lib/i18n'

const LanguageContext = createContext({ language: 'fr', setLanguage: () => {}, t: (k) => k, pick: (l) => (Array.isArray(l) ? l[0] : l || '') })

function initialLanguage() {
  try {
    const stored = localStorage.getItem('language')
    if (stored === 'fr' || stored === 'en') return stored
  } catch {
    /* stockage indisponible */
  }
  return 'fr'
}

export function LanguageProvider({ children }) {
  const [language, setLanguageState] = useState(initialLanguage)

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const setLanguage = useCallback((next) => {
    setLanguageState(next)
    try {
      localStorage.setItem('language', next)
    } catch {
      /* préférence non persistée */
    }
  }, [])

  const t = useCallback((key, vars) => translate(language, key, vars), [language])
  // Libellés venus du serveur ([français, anglais]) : modules, pages, champs, chiffres clés
  const pick = useCallback((label, vars) => pickLabel(language, label, vars), [language])
  const value = useMemo(() => ({ language, setLanguage, t, pick }), [language, setLanguage, t, pick])
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export const useLanguage = () => useContext(LanguageContext)
