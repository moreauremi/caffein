// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from 'react-router-dom'
import { useLanguage } from '../context/LanguageContext'
import { duration, money, number } from '../lib/format'
import NamedIcon from './NamedIcon'

// Chiffre clé d'un module, déjà calculé par le serveur : on ne fait que le mettre en forme
function kpiValue(kpi, language) {
  if (kpi.value === null || kpi.value === undefined) return '—'
  if (kpi.unit === 'money') return money(kpi.value, language)
  if (kpi.unit === 'minutes') return duration(kpi.value, language)
  if (kpi.unit === 'percent') return `${number(kpi.value, language, 1)} %`
  if (kpi.unit === 'days') return `${number(kpi.value, language, 1)} j`
  return number(kpi.value, language, 2)
}

export default function KpiCard({ kpi, title, link = true }) {
  const { pick, language } = useLanguage()
  const body = (
    <div className={`card stat kpi ${kpi.alert ? 'dark' : ''}`}>
      <div className="stat-label">
        {kpi.icon ? <span className="stat-icon"><NamedIcon name={kpi.icon} /></span> : null}
        {title || pick(kpi.label)}
      </div>
      <div className="stat-value">{kpiValue(kpi, language)}</div>
      {kpi.foot ? <div className="stat-foot">{pick(kpi.foot, { n: kpi.count ?? 0 })}</div> : null}
    </div>
  )
  return link && kpi.path ? <Link to={kpi.path} className="kpi-link">{body}</Link> : body
}
