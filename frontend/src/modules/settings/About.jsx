// SPDX-License-Identifier: AGPL-3.0-or-later
import { Database, ExternalLink, Scale } from 'lucide-react'
import { Spinner } from '../../components/ui'
import { useApp } from '../../context/AppContext'
import { useLanguage } from '../../context/LanguageContext'
import SettingsPage from './SettingsPage'

export default function About() {
  const { t } = useLanguage()
  const { config } = useApp()
  if (!config) return <Spinner />
  return (
    <SettingsPage title={t('settings.tab_about')}>
    <div className="stack lg" style={{ maxWidth: 720 }}>
      <div className="card tight" style={{ boxShadow: 'none' }}>
        <div className="row" style={{ gap: 12 }}>
          <span className="stat-icon"><Scale size={16} /></span>
          <div className="grow">
            <div style={{ fontWeight: 650 }}>Caffein {config.version}</div>
            <div className="small muted">{t('about.license', { license: config.license })}</div>
          </div>
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>{t('about.agpl')}</p>
        {config.source_url ? (
          <a className="btn sm" style={{ marginTop: 12 }} href={config.source_url} target="_blank" rel="noreferrer">
            <ExternalLink size={14} /> {t('about.source')}
          </a>
        ) : (
          <p className="xsmall subtle" style={{ marginTop: 10 }}>{t('about.source_missing')}</p>
        )}
      </div>
      <div className="stack sm small">
        {[
          [t('auto.ai'), config.ai.mode === 'claude' ? `Claude · ${config.ai.model}` : t('auto.ai_offline')],
          [t('auto.email'), config.email.provider || t('auto.email_sim')],
          [t('auto.scheduler'), config.scheduler ? t('auto.scheduler_on') : t('auto.scheduler_off')],
          [t('about.schema'), `v${config.schema}`],
          [t('about.url'), config.app_url],
        ].map(([label, value]) => (
          <div className="row between" key={label} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
            <span className="muted">{label}</span><span className="small" style={{ textAlign: 'right' }}>{value}</span>
          </div>
        ))}
      </div>
      <p className="xsmall subtle row" style={{ gap: 6 }}><Database size={13} /> {t('about.backup_hint')}</p>
    </div>
    </SettingsPage>
  )
}
