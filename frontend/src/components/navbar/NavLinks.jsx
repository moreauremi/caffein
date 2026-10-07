// SPDX-License-Identifier: AGPL-3.0-or-later
import { NavLink } from 'react-router-dom'
import { Bot, FileStack, Home, Landmark, Percent, ReceiptText } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'

const LINKS = [
  { to: '/', key: 'nav.home', icon: Home, end: true },
  { to: '/tva', key: 'nav.tva', icon: Percent },
  { to: '/factures', key: 'nav.invoices', icon: ReceiptText },
  { to: '/documents', key: 'nav.documents', icon: FileStack },
  { to: '/urssaf', key: 'nav.urssaf', icon: Landmark },
  { to: '/automatisations', key: 'nav.automations', icon: Bot },
]

export default function NavLinks({ className = 'navlinks' }) {
  const { t } = useLanguage()
  return (
    <nav className={className} aria-label={t('nav.label')}>
      {LINKS.map(({ to, key, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className={({ isActive }) => `navlink ${isActive ? 'active' : ''}`}>
          <Icon size={16} />
          {t(key)}
        </NavLink>
      ))}
    </nav>
  )
}
