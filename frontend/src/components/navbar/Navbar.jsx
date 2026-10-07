// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from 'react-router-dom'
import { Moon, Sun } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { useTheme } from '../../context/ThemeContext'
import Logo from '../Logo'
import NavLinks from './NavLinks'
import UserMenu from './UserMenu'

export default function Navbar() {
  const { theme, toggleTheme } = useTheme()
  const { t } = useLanguage()
  return (
    <header className="navbar">
      <div className="container navbar-inner">
        <Link to="/" style={{ textDecoration: 'none' }} aria-label="Caffein"><Logo size={28} /></Link>
        <NavLinks />
        <div className="nav-right">
          <button className="icon-btn" onClick={toggleTheme} aria-label={theme === 'clair' ? t('user.dark') : t('user.light')}>
            {theme === 'clair' ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <UserMenu />
        </div>
      </div>
      <NavLinks className="mobile-nav" />
    </header>
  )
}
