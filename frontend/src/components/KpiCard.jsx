// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from 'react-router-dom'
import { useLanguage } from '../context/LanguageContext'
import { kpiValue } from '../lib/kpi'
import NamedIcon from './NamedIcon'

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
