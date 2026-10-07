// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Info, LogOut, Moon, Settings, Sun, UserRound } from 'lucide-react'
import { useApp } from '../../context/AppContext'
import { useAuth } from '../../context/AuthContext'
import { useLanguage } from '../../context/LanguageContext'
import { useTheme } from '../../context/ThemeContext'
import { initials } from '../../lib/format'

export default function UserMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { profile, openSettings } = useApp()
  const { user, signOut } = useAuth()
  const { t } = useLanguage()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return undefined
    const onClick = (e) => !ref.current?.contains(e.target) && setOpen(false)
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const go = (tab) => { setOpen(false); openSettings(tab) }
  const name = user?.full_name || user?.email || ''
  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn" style={{ width: 'auto', padding: 2, borderRadius: 999 }} onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu" aria-expanded={open} aria-label={t('user.menu')}>
        <span className="avatar">{initials(name)}</span>
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <div className="menu-head">
            <div className="row between" style={{ gap: 8 }}>
              <div style={{ fontWeight: 650 }} className="truncate">{name || '—'}</div>
              <span className={`badge ${user?.role === 'admin' ? 'accent' : ''}`}>{t(`role.${user?.role || 'member'}`)}</span>
            </div>
            <div className="small muted truncate">{user?.email}</div>
            {profile?.company && <div className="xsmall subtle truncate" style={{ marginTop: 2 }}>{profile.company}</div>}
          </div>
          <button className="menu-item" role="menuitem" onClick={() => go('me')}><UserRound size={16} /> {t('user.account')}</button>
          {user?.role === 'admin' && (
            <button className="menu-item" role="menuitem" onClick={() => go('company')}><Settings size={16} /> {t('user.settings')}</button>
          )}
          <button className="menu-item" role="menuitem" onClick={toggleTheme}>
            {theme === 'clair' ? <Moon size={16} /> : <Sun size={16} />}
            {theme === 'clair' ? t('user.dark') : t('user.light')}
          </button>
          <button className="menu-item" role="menuitem" onClick={() => go('about')}><Info size={16} /> {t('user.about')}</button>
          <button className="menu-item danger" role="menuitem" onClick={async () => { await signOut(); navigate('/login') }}>
            <LogOut size={16} /> {t('user.logout')}
          </button>
        </div>
      )}
    </div>
  )
}
