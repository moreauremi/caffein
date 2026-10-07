// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, ArrowRight, Bot, CalendarClock, Clock3, FileStack, Landmark, Newspaper, Percent, Plus, ReceiptText,
  ScanLine, Upload, Wallet,
} from 'lucide-react'
import Greeting from '../components/Greeting'
import { JOB_ICONS } from '../components/jobIcons'
import { EmptyState, StatCard } from '../components/ui'
import { useApp } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import { useLanguage } from '../context/LanguageContext'
import { date, daysFromNow, duration, money, relative } from '../lib/format'
import { useApi } from '../lib/useApi'

export default function Home() {
  const { t, language } = useLanguage()
  const { profile } = useApp()
  const { user } = useAuth()
  const { data, loading, reload } = useApi('/api/home')

  // Des documents sont en attente dans « Factures à traiter » : on rafraîchit jusqu'à leur traitement
  useEffect(() => {
    if (!data?.inbox_count) return undefined
    const timer = setInterval(reload, 4000)
    return () => clearInterval(timer)
  }, [data?.inbox_count, reload])

  const s = data?.stats
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <Greeting name={user?.full_name || profile?.full_name} />
          <p className="page-sub">{t('home.subtitle')}</p>
        </div>
        <div className="row wrap">
          <Link to="/documents" className="btn"><Upload size={16} /> {t('home.upload')}</Link>
          <Link to="/factures?new=invoice" className="btn primary"><Plus size={16} /> {t('home.new_invoice')}</Link>
        </div>
      </div>

      {data?.inbox_count > 0 && (
        <div className="alert info" style={{ marginBottom: 18 }}>
          <ScanLine size={18} />
          <span>{t('home.inbox_processing', { n: data.inbox_count })}</span>
        </div>
      )}

      <div className="grid grid-4">
        <StatCard icon={FileStack} label={t('home.stat_documents')} value={s?.documents ?? '—'} loading={loading}
          foot={t('home.stat_documents_foot')} />
        <StatCard icon={Percent} label={t('home.stat_tva')} value={money(s?.tva_collected, language)} loading={loading}
          foot={t('home.this_month')} />
        <StatCard icon={Landmark} label={t('home.stat_balance')} value={money(s?.balance, language)} loading={loading}
          dark={s?.balance > 0} foot={s?.balance > 0 ? t('home.stat_balance_due') : t('home.stat_balance_credit')} />
        <StatCard icon={Clock3} label={t('home.stat_time')} value={duration(s?.time_saved_min, language)} loading={loading}
          foot={t('home.stat_time_foot')} />
      </div>

      <div className="grid grid-main section-gap">
        <div className="stack lg">
          <div className="grid grid-2">
            <div className="card">
              <div className="card-head">
                <div className="card-title"><Wallet size={16} /> {t('home.to_collect')}</div>
                <Link to="/factures" className="link small">{t('common.see_all')} <ArrowRight size={14} /></Link>
              </div>
              <div className="amount-big">{money(s?.to_collect, language)}</div>
              <div className="small muted" style={{ marginTop: 8 }}>{t('home.to_collect_count', { n: s?.to_collect_count ?? 0 })}</div>
              {s?.overdue_count > 0 ? (
                <Link to="/factures?status=overdue" className="alert bad small" style={{ marginTop: 16, textDecoration: 'none' }}>
                  <AlertTriangle size={16} />
                  <span>{t('home.overdue', { n: s.overdue_count, amount: money(s.overdue_total, language) })}</span>
                </Link>
              ) : (
                <div className="small muted" style={{ marginTop: 16 }}>{t('home.no_overdue')}</div>
              )}
              <div className="small muted" style={{ marginTop: 12 }}>
                {t('home.paid_month')} <span className="mono" style={{ color: 'var(--fg)' }}>{money(s?.paid_month, language)}</span>
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <div className="card-title"><CalendarClock size={16} /> {t('home.deadlines')}</div>
              </div>
              {data?.next_deadlines?.length ? (
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
              ) : <EmptyState icon={CalendarClock} title={t('home.no_deadline')} />}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div className="card-title"><Bot size={16} /> {t('home.activity')}</div>
              <Link to="/automatisations" className="link small">{t('home.activity_all')} <ArrowRight size={14} /></Link>
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
          <Link to="/factures" className="btn block" style={{ marginTop: 16 }}><ReceiptText size={16} /> {t('home.cta_invoices')}</Link>
        </div>
      </div>
    </div>
  )
}
