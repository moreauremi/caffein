// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link, useLocation } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { moduleForPath, pagePath } from '../../lib/meta'
import Logo from '../Logo'
import NamedIcon from '../NamedIcon'

function ModuleLink({ module, active, collapsed, onNavigate }) {
  const { pick } = useLanguage()
  const label = pick(module.label)
  return (
    <Link to={pagePath(module, module.pages[0])} className={`side-link ${active ? 'active' : ''}`} onClick={onNavigate}
      aria-current={active ? 'page' : undefined} title={collapsed ? label : undefined}>
      <NamedIcon name={module.icon} size={18} />
      <span className="side-label">{label}</span>
    </Link>
  )
}

// Navigation entre modules : seulement ceux que l'utilisateur peut voir (décidé par le serveur, /api/meta).
export default function Sidebar({ open, collapsed, onClose, onToggleCollapse }) {
  const { t } = useLanguage()
  const { modules } = useMeta()
  const { pathname } = useLocation()
  const current = moduleForPath(modules, pathname)
  const main = modules.filter((m) => m.key !== 'settings')
  const settings = modules.find((m) => m.key === 'settings')

  return (
    <>
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label={t('nav.label')}>
        <div className="sidebar-head">
          <Link to="/" className="sidebar-logo" aria-label="Caffein" onClick={onClose}><Logo size={26} wordmark={!collapsed} /></Link>
          <button type="button" className="icon-btn sidebar-close" onClick={onClose} aria-label={t('nav.close_menu')}><X size={18} /></button>
        </div>
        <nav className="sidebar-nav" aria-label={t('nav.modules')}>
          {main.map((m) => <ModuleLink key={m.key} module={m} active={current?.key === m.key} collapsed={collapsed} onNavigate={onClose} />)}
        </nav>
        <div className="sidebar-foot">
          {settings && <ModuleLink module={settings} active={current?.key === 'settings'} collapsed={collapsed} onNavigate={onClose} />}
          <button type="button" className="side-link side-collapse" onClick={onToggleCollapse}
            aria-label={collapsed ? t('nav.expand') : t('nav.collapse')} title={collapsed ? t('nav.expand') : undefined}>
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            <span className="side-label">{t('nav.collapse')}</span>
          </button>
        </div>
      </aside>
      {open && <div className="overlay sidebar-overlay" onClick={onClose} aria-hidden="true" />}
    </>
  )
}
