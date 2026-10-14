// SPDX-License-Identifier: AGPL-3.0-or-later
import { Spinner, Toggle } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import SaveButton from './SaveButton'
import SettingsPage from './SettingsPage'
import { useProfileForm } from './useProfileForm'

export default function Notifications() {
  const { t } = useLanguage()
  const { profile, form, setForm, set, dirty, saving, save } = useProfileForm()
  return (
    <SettingsPage title={t('settings.tab_notifications')} actions={<SaveButton onClick={save} disabled={!dirty} saving={saving} />}>
      {!profile ? <Spinner /> : (
        <div className="card" style={{ maxWidth: 820 }}>
          <div>
            <div className="toggle-row">
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{t('settings.notif_tva')}</div>
                <div className="small muted">{t('settings.notif_tva_hint')}</div>
                {form.notif_tva && (
                  <div className="row" style={{ marginTop: 10, maxWidth: 260 }}>
                    <span className="small muted nowrap">{t('settings.threshold')}</span>
                    <input className="input sm num mono" type="number" min="0" step="50" value={form.tva_alert_threshold}
                      onChange={(e) => setForm((f) => ({ ...f, tva_alert_threshold: Number(e.target.value) }))} />
                    <span className="small muted">€</span>
                  </div>
                )}
              </div>
              <Toggle checked={form.notif_tva} onChange={set('notif_tva')} label={t('settings.notif_tva')} />
            </div>
            {[
              ['notif_echeance', 'settings.notif_echeance', 'settings.notif_echeance_hint'],
              ['notif_hebdo', 'settings.notif_hebdo', 'settings.notif_hebdo_hint'],
              ['notif_onboarding', 'settings.notif_onboarding', 'settings.notif_onboarding_hint'],
            ].map(([key, label, hint]) => (
              <div className="toggle-row" key={key}>
                <div>
                  <div style={{ fontWeight: 600 }}>{t(label)}</div>
                  <div className="small muted">{t(hint)}</div>
                </div>
                <Toggle checked={form[key]} onChange={set(key)} label={t(label)} />
              </div>
            ))}
            <p className="xsmall subtle" style={{ marginTop: 12 }}>{t('settings.notif_footer', { email: form.email || '—' })}</p>
          </div>
        </div>
      )}
    </SettingsPage>
  )
}
