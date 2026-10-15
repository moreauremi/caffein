// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Blocks, Bot, CalendarClock, Landmark, Newspaper, Percent, ScanLine } from 'lucide-react'
import Greeting from '../../components/Greeting'
import { JOB_ICONS } from '../../components/jobIcons'
import KpiCard from '../../components/KpiCard'
import NamedIcon from '../../components/NamedIcon'
import { EmptyState } from '../../components/ui'
import { useApp } from '../../context/AppContext'
import { useAuth } from '../../context/AuthContext'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { date, daysFromNow, money, relative } from '../../lib/format'
import { kpiValue } from '../../lib/kpi'
import { pagePath } from '../../lib/meta'
import { useApi } from '../../lib/useApi'

export default function Dashboard() {
  const { t, pick, language } = useLanguage()
  const { profile } = useApp()
  const { user } = useAuth()
  const { modules } = useMeta()
  const { data, loading, reload } = useApi('/api/home')

  // Des documents sont en attente dans « Factures à traiter » : on rafraîchit jusqu'à leur traitement
  useEffect(() => {
    if (!data?.inbox_count) return undefined
    const timer = setInterval(reload, 4000)
    return () => clearInterval(timer)
  }, [data?.inbox_count, reload])

  // Ce qui demande une action (retards, ruptures, validations) en tête, puis une carte par module
  const alerts = (data?.kpis || []).filter((k) => k.alert)
  const groups = [...modules.filter((m) => m.key !== 'home'), ...modules.filter((m) => m.key === 'home')]
    .map((m) => ({ module: m, kpis: (data?.kpis || []).filter((k) => k.module === m.key) }))
    .filter((g) => g.kpis.length)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <Greeting name={user?.full_name || profile?.full_name} />
          <p className="page-sub">{t('home.subtitle')}</p>
        </div>
      </div>

      {data?.shortcuts?.length ? (
        <nav className="shortcuts" aria-label={t('home.shortcuts')}>
          {data.shortcuts.map((s, i) => (
            <Link key={s.key} to={s.path} className={`btn sm ${i === 0 ? 'primary' : ''}`}>
              {s.icon ? <NamedIcon name={s.icon} size={15} /> : null} {pick(s.label)}
            </Link>
          ))}
        </nav>
      ) : null}

      {data?.inbox_count > 0 && (
        <div className="alert info" style={{ marginBottom: 18 }}>
          <ScanLine size={18} />
          <span>{t('home.inbox_processing', { n: data.inbox_count })}</span>
        </div>
      )}

      {loading && !data ? (
        <div className="grid grid-4">{[0, 1, 2, 3].map((i) => <div key={i} className="card stat"><div className="skeleton" style={{ height: 60 }} /></div>)}</div>
      ) : null}
      {data && !groups.length ? <EmptyState title={t('home.no_kpi')} /> : null}

      {alerts.length ? (
        <section className="kpi-group" aria-label={t('home.to_handle')}>
          <h2 className="kpi-group-title"><AlertTriangle size={15} /> {t('home.to_handle')}</h2>
          <div className="grid grid-4">{alerts.map((kpi) => <KpiCard key={kpi.key} kpi={kpi} />)}</div>
        </section>
      ) : null}

      {groups.length ? (
        <section className="kpi-group" aria-label={t('home.modules_title')}>
          <h2 className="kpi-group-title"><Blocks size={15} /> {t('home.modules_title')}</h2>
          <div className="module-cards">
            {groups.map(({ module, kpis }) => (
              <div className="card module-summary" key={module.key}>
                <Link className="module-summary-head" to={pagePath(module, module.pages[0])}>
                  <span className="module-icon sm"><NamedIcon name={module.icon} size={16} /></span>
                  <span className="grow">{pick(module.label)}</span>
                  <ArrowRight size={14} />
                </Link>
                <ul className="kpi-rows">
                  {kpis.map((kpi) => (
                    <li key={kpi.key}>
                      <Link to={kpi.path || pagePath(module, module.pages[0])} className={`kpi-row ${kpi.alert ? 'alert' : ''}`}
                        title={kpi.foot ? pick(kpi.foot, { n: kpi.count ?? 0 }) : undefined}>
                        <span className="grow">{pick(kpi.label)}</span>
                        <span className="mono nowrap">{kpiValue(kpi, language)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <div className="grid grid-main section-gap">
        <div className="stack lg">
          {data?.next_deadlines?.length ? (
            <div className="card">
              <div className="card-head">
                <div className="card-title"><CalendarClock size={16} /> {t('home.deadlines')}</div>
              </div>
              <div className="list">
                {data.next_deadlines.map((d) => (
                  <Link to={d.path} key={d.type} className="list-item" style={{ textDecoration: 'none' }}>
                    <span className="list-icon">{d.type === 'tva' ? <Percent size={16} /> : <Landmark size={16} />}</span>
                    <div className="grow">
                      <div className="small truncate" style={{ fontWeight: 600 }}>{d.label}</div>
                      <div className="xsmall muted">{date(d.date, language, 'long')} · {daysFromNow(d.date, language)}</div>
                    </div>
                    <span className="mono small">{money(d.amount, language)}</span>
                  </Link>
                ))}
              </div>
            </div>
          ) : null}

          <div className="card">
            <div className="card-head">
              <div className="card-title"><Bot size={16} /> {t('home.activity')}</div>
              <Link to="/parametres/automatisations" className="link small">{t('home.activity_all')} <ArrowRight size={14} /></Link>
            </div>
            {data?.activity?.length ? (
              <div className="list">
                {data.activity.map((a) => {
                  const Icon = JOB_ICONS[a.job] || Bot
                  return (
                    <div className="list-item" key={a.id}>
                      <span className="list-icon" style={a.status === 'error' ? { color: 'var(--bad)' } : undefined}><Icon size={16} /></span>
                      <div className="grow">
                        <div className="small truncate" style={{ fontWeight: 550 }}>{a.summary}</div>
                        <div className="xsmall muted">{t(`jobs.${a.job}.title`)} · {relative(a.started_at, language)}</div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : <EmptyState icon={Bot} title={t('home.no_activity')} />}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title"><Newspaper size={16} /> {t('home.news')}</div>
          </div>
          {data?.notifications?.length ? (
            <div className="stack">
              {data.notifications.map((n) => (
                <article key={n.id} className="card tight" style={{ boxShadow: 'none', background: 'var(--surface-2)' }}>
                  <div className="row between" style={{ marginBottom: 8 }}>
                    <span className="pill-tag" style={{ background: n.color, color: n.tag_color }}>{n.tag}</span>
                    <span className="xsmall muted">{relative(n.created_at, language)}</span>
                  </div>
                  <div style={{ fontWeight: 650 }}>{n.title}</div>
                  <p className="small muted" style={{ marginTop: 4 }}>{n.description}</p>
                </article>
              ))}
            </div>
          ) : <EmptyState icon={Newspaper} title={t('home.no_news')} />}
        </div>
      </div>
    </div>
  )
}
