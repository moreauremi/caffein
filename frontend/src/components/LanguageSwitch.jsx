// SPDX-License-Identifier: AGPL-3.0-or-later
import { Moon, Sun } from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'
import { useTheme } from '../context/ThemeContext'

export default function LanguageSwitch() {
  const { language, setLanguage, t } = useLanguage()
  const { theme, toggleTheme } = useTheme()
  return (
    <>
      <button className="icon-btn" onClick={() => setLanguage(language === 'fr' ? 'en' : 'fr')} aria-label="Langue / Language">
        <span className="xsmall" style={{ fontWeight: 700 }}>{language === 'fr' ? 'EN' : 'FR'}</span>
      </button>
      <button className="icon-btn" onClick={toggleTheme} aria-label={t(theme === 'clair' ? 'user.dark' : 'user.light')}>
        {theme === 'clair' ? <Moon size={17} /> : <Sun size={17} />}
      </button>
    </>
  )
}
