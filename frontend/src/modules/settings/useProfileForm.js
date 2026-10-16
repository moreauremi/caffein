// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useApp } from '../../context/AppContext'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'

// Formulaire sur le profil de l'entreprise (pages Entreprise, Fiscalité, Notifications)
export function useProfileForm() {
  const { profile, setProfile } = useApp()
  const { t } = useLanguage()
  const toast = useToast()
  const [form, setForm] = useState(profile || {})
  const [synced, setSynced] = useState(profile)
  const [saving, setSaving] = useState(false)
  if (profile !== synced) {
    // profil rechargé (sauvegarde, réinitialisation) : on resynchronise le formulaire
    setSynced(profile)
    setForm(profile || {})
  }
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e?.target ? e.target.value : e }))
  const dirty = Boolean(profile) && JSON.stringify(form) !== JSON.stringify(profile)

  async function save() {
    setSaving(true)
    try {
      setProfile(await api.put('/api/profile', form))
      toast(t('settings.saved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return { profile, form, setForm, set, dirty, saving, save }
}
