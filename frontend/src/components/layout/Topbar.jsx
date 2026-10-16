// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Menu, Moon, Sun } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { useTheme } from '../../context/ThemeContext'
import { moduleForPath, pagePath } from '../../lib/meta'
import NamedIcon from '../NamedIcon'
import UserMenu from '../navbar/UserMenu'

// Barre du haut : module en cours, ses pages en onglets, thème et compte.
export default function Topbar({ onMenu }) {
  const { t, pick } = useLanguage()
  const { theme, toggleTheme } = useTheme()
  const { modules } = useMeta()
  const { pathname } = useLocation()
  const current = moduleForPath(modules, pathname)
  const title = current ? pick(current.label) : ''

  // Titre de l'onglet du navigateur : le module en cours
  useEffect(() => {
    document.title = title ? `${title} · Caffein` : 'Caffein'
  }, [title])

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <button type="button" className="icon-btn topbar-menu" onClick={onMenu} aria-label={t('nav.open_menu')}><Menu size={20} /></button>
        <div className="topbar-title">
          {current ? <><NamedIcon name={current.icon} size={18} /> <span className="truncate">{pick(current.label)}</span></> : null}
        </div>
        <div className="nav-right">
          <button className="icon-btn" onClick={toggleTheme} aria-label={theme === 'clair' ? t('user.dark') : t('user.light')}>
            {theme === 'clair' ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <UserMenu />
        </div>
      </div>
      {current && current.pages.length > 1 && (
        <nav className="page-tabs" aria-label={t('nav.pages')}>
          {current.pages.map((page) => (
            <NavLink key={page.slug} to={pagePath(current, page)} end={page.path === '/'}
              className={({ isActive }) => `page-tab ${isActive ? 'active' : ''}`}>
              {page.icon ? <NamedIcon name={page.icon} size={15} /> : null}
              {pick(page.label)}
            </NavLink>
          ))}
        </nav>
      )}
    </header>
  )
}
