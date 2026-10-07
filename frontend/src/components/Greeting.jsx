// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLanguage } from '../context/LanguageContext'
import { capitalize, date } from '../lib/format'

// Message de bienvenue selon l'heure : 5h–12h, 12h–18h, 18h–5h
export default function Greeting({ name }) {
  const { t, language } = useLanguage()
  const hour = new Date().getHours()
  const key = hour >= 5 && hour < 12 ? 'morning' : hour >= 12 && hour < 18 ? 'afternoon' : 'evening'
  const first = (name || '').split(' ')[0]
  const today = capitalize(date(new Date(), language, 'day'))
  return (
    <div>
      <div className="small muted" style={{ marginBottom: 6 }}>{today}</div>
      <h1 className="page-title">
        {t(`greeting.${key}`)}{first ? <> <span className="serif" style={{ fontStyle: 'italic' }}>{first}</span></> : ''}
      </h1>
    </div>
  )
}
