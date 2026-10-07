// SPDX-License-Identifier: AGPL-3.0-or-later
import { BellRing, Landmark, MessageSquareText } from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'
import Logo from './Logo'

// Panneau de marque des pages de connexion et d'installation
export default function AuthAside() {
  const { t } = useLanguage()
  return (
    <aside className="auth-side">
      <div className="auth-glow" aria-hidden="true" />
      <div className="auth-side-inner">
        <Logo size={30} />
        <div>
          <h1 className="auth-title">{t('auth.title_1')} <em>{t('auth.title_2')}</em></h1>
          <div className="stack" style={{ marginTop: 30, gap: 14 }}>
            {[[MessageSquareText, 'auth.f1'], [BellRing, 'auth.f2'], [Landmark, 'auth.f3']].map(([Icon, key]) => (
              <div className="row" key={key} style={{ gap: 12, color: 'rgba(245,245,242,0.8)' }}>
                <span className="auth-icon"><Icon size={16} /></span>{t(key)}
              </div>
            ))}
          </div>
        </div>
        <div className="small" style={{ color: 'rgba(245,245,242,0.5)' }}>{t('auth.side_foot')}</div>
      </div>
    </aside>
  )
}
