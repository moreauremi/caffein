// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../lib/api'

// Données partagées de l'espace connecté : profil, configuration serveur, ouverture des paramètres.
const AppContext = createContext(null)

export function AppProvider({ children }) {
  const [profile, setProfile] = useState(null)
  const [config, setConfig] = useState(null)
  const [settingsTab, setSettingsTab] = useState(null)

  const refresh = useCallback(async () => {
    const [p, c] = await Promise.all([api.get('/api/profile'), api.get('/api/config')])
    setProfile(p)
    setConfig(c)
  }, [])

  useEffect(() => {
    Promise.all([api.get('/api/profile'), api.get('/api/config')])
      .then(([p, c]) => {
        setProfile(p)
        setConfig(c)
      })
      .catch(() => {})
  }, [])

  const value = {
    profile, setProfile, config, refresh,
    settingsTab, openSettings: (tab = 'me') => setSettingsTab(tab), closeSettings: () => setSettingsTab(null),
  }
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export const useApp = () => useContext(AppContext)
