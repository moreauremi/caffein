// SPDX-License-Identifier: AGPL-3.0-or-later
import { Segmented } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import { useTheme } from '../../context/ThemeContext'
import SettingsPage from './SettingsPage'

export default function Appearance() {
  const { t, language, setLanguage } = useLanguage()
  const { theme, setTheme } = useTheme()
  return (
    <SettingsPage title={t('settings.tab_appearance')}>
      <div className="card" style={{ maxWidth: 720 }}>
        <div className="toggle-row">
          <div>
            <div style={{ fontWeight: 600 }}>{t('settings.theme')}</div>
            <div className="small muted">{t('settings.theme_hint')}</div>
          </div>
          <Segmented value={theme} onChange={setTheme} label={t('settings.theme')}
            options={[{ value: 'clair', label: t('settings.light') }, { value: 'sombre', label: t('settings.dark') }]} />
        </div>
        <div className="toggle-row">
          <div>
            <div style={{ fontWeight: 600 }}>{t('settings.language')}</div>
            <div className="small muted">{t('settings.language_hint')}</div>
          </div>
          <Segmented value={language} onChange={setLanguage} label={t('settings.language')}
            options={[{ value: 'fr', label: 'Français' }, { value: 'en', label: 'English' }]} />
        </div>
      </div>
    </SettingsPage>
  )
}
