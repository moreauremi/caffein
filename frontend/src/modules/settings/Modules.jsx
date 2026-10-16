// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import NamedIcon from '../../components/NamedIcon'
import { Spinner, Toggle } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { useApi } from '../../lib/useApi'
import SettingsPage from './SettingsPage'

// Activation des modules de l'instance (administrateurs). Le serveur vérifie les dépendances.
export default function Modules() {
  const { t, pick } = useLanguage()
  const toast = useToast()
  const { reload: reloadMeta } = useMeta()
  const { data: modules, setData } = useApi('/api/settings/modules')
  const [busy, setBusy] = useState(null)
  const byKey = Object.fromEntries((modules || []).map((m) => [m.key, m]))
  const names = (keys) => keys.map((k) => pick(byKey[k]?.label) || k).join(', ')

  async function toggle(module, enabled) {
    setBusy(module.key)
    try {
      setData(await api.put(`/api/settings/modules/${module.key}`, { enabled }))
      await reloadMeta()
      toast(t(enabled ? 'modules.enabled' : 'modules.disabled'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <SettingsPage title={t('modules.title')} lead={t('modules.lead')} wide>
      {!modules ? <Spinner /> : (
        <div className="grid grid-2 modules-grid">
          {modules.map((m) => (
            <div key={m.key} className={`card module-card ${m.enabled ? 'on' : ''}`}>
              <div className="row" style={{ alignItems: 'flex-start', gap: 14 }}>
                <span className="module-icon"><NamedIcon name={m.icon} size={20} /></span>
                <div className="grow">
                  <div className="row between" style={{ gap: 10 }}>
                    <h2 className="card-title" style={{ margin: 0 }}>{pick(m.label)}</h2>
                    {m.core ? <span className="badge outline">{t('modules.core')}</span> : (
                      busy === m.key ? <Spinner /> : (
                        <Toggle checked={m.enabled} label={t('modules.toggle', { name: pick(m.label) })} onChange={(v) => toggle(m, v)} />
                      )
                    )}
                  </div>
                  <p className="small muted" style={{ marginTop: 6 }}>{pick(m.description)}</p>
                  {m.pages.length ? (
                    <p className="xsmall subtle" style={{ marginTop: 8 }}>{t('modules.contains', { names: m.pages.map((p) => pick(p.label)).join(', ') })}</p>
                  ) : null}
                  {m.depends.length ? <p className="xsmall subtle">{t('modules.depends', { names: names(m.depends) })}</p> : null}
                  {m.dependents.length ? <p className="xsmall subtle">{t('modules.used_by', { names: names(m.dependents) })}</p> : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </SettingsPage>
  )
}
