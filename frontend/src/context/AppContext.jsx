// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

// Données partagées de l'espace connecté : profil de l'entreprise, configuration serveur.
const AppContext = createContext(null)

// Anciens onglets du panneau de paramètres → pages du module Paramètres
const SETTINGS_PAGES = {
  me: 'compte', appearance: 'apparence', company: 'entreprise', fiscal: 'fiscalite', notifications: 'notifications',
  users: 'utilisateurs', roles: 'roles', modules: 'modules', automations: 'automatisations', about: 'a-propos',
}

export function AppProvider({ children }) {
  const navigate = useNavigate()
  const [profile, setProfile] = useState(null)
  const [config, setConfig] = useState(null)

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

  const openSettings = useCallback((tab = 'me') => navigate(`/parametres/${SETTINGS_PAGES[tab] || 'compte'}`), [navigate])

  const value = { profile, setProfile, config, refresh, openSettings }
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export const useApp = () => useContext(AppContext)
