// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const ThemeContext = createContext({ theme: 'clair', toggleTheme: () => {}, setTheme: () => {} })

function initialTheme() {
  try {
    const stored = localStorage.getItem('theme')
    if (stored === 'clair' || stored === 'sombre') return stored
  } catch {
    /* stockage indisponible */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'sombre' : 'clair'
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(initialTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const setTheme = useCallback((next) => {
    setThemeState(next)
    try {
      localStorage.setItem('theme', next)
    } catch {
      /* préférence non persistée */
    }
  }, [])

  const toggleTheme = useCallback(() => setTheme(theme === 'clair' ? 'sombre' : 'clair'), [theme, setTheme])

  return <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>{children}</ThemeContext.Provider>
}

export const useTheme = () => useContext(ThemeContext)
