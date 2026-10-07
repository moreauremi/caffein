// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import {
  BarChart3, CalendarClock, ChevronLeft, ChevronRight, CircleCheck, ExternalLink, Gauge, HandCoins, Info, Landmark,
  PiggyBank, Undo2, Wallet,
} from 'lucide-react'
import { BarsChart } from '../components/charts'
import { DeclarationStatus, Spinner, StatCard } from '../components/ui'
import { useApp } from '../context/AppContext'
import { useLanguage } from '../context/LanguageContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'
import { date, daysFromNow, money, percent } from '../lib/format'
import { useApi } from '../lib/useApi'

function Threshold({ label, value, limit, ratio, language }) {
  const cls = ratio >= 1 ? 'bad' : ratio >= 0.8 ? 'warn' : 'accent'
  return (
    <div>
      <div className="row between small" style={{ marginBottom: 8 }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span className="mono muted">{money(value, language, { decimals: 0 })} / {money(limit, language, { decimals: 0 })}</span>
      </div>
      <div className={`progress ${cls}`} role="progressbar" aria-label={label} aria-valuenow={Math.round(ratio * 100)} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${Math.min(100, ratio * 100)}%` }} />
      </div>
      <div className="xsmall muted" style={{ marginTop: 6 }}>{percent(ratio, language)}</div>
    </div>
  )
}

export default function Urssaf() {
  const { t, language } = useLanguage()
  const { config, openSettings } = useApp()
  const toast = useToast()
  const currentYear = Number((config?.today || new Date().toISOString()).slice(0, 4))
  const [year, setYear] = useState(currentYear)
  const { data, setData } = useApi(`/api/urssaf?year=${year}`)
  const [busy, setBusy] = useState('')

  async function declare(period, declared) {
    setBusy(period.key)
    try {
      setData(await api.post('/api/urssaf/declarations', { period_key: period.key, declared }))
      toast(declared ? t('urssaf.declared_toast', { period: period.label }) : t('urssaf.undeclared_toast'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const next = data?.next
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('urssaf.title')}</h1>
          <p className="page-sub">{t('urssaf.subtitle')}</p>
        </div>
        <div className="row">
          <button className="icon-btn bordered" onClick={() => setYear((y) => y - 1)} aria-label={t('urssaf.prev_year')}><ChevronLeft size={18} /></button>
          <span className="mono" style={{ fontWeight: 600, minWidth: 48, textAlign: 'center' }}>{year}</span>
          <button className="icon-btn bordered" onClick={() => setYear((y) => y + 1)} disabled={year >= currentYear} aria-label={t('urssaf.next_year')}><ChevronRight size={18} /></button>
        </div>
      </div>

      {next && (
        <div className="card" style={{ marginBottom: 16, borderColor: next.status === 'late' ? 'color-mix(in srgb, var(--bad) 40%, transparent)' : undefined }}>
          <div className="row between wrap" style={{ gap: 20, alignItems: 'flex-start' }}>
            <div>
              <div className="row" style={{ gap: 8, marginBottom: 10 }}>
                <span className="card-title"><CalendarClock size={16} /> {t('urssaf.next')}</span>
                <DeclarationStatus status={next.status} />
              </div>
              <div className="small muted">{next.label}</div>
              <div className="amount-big" style={{ marginTop: 8 }}>{money(next.ca, language)}</div>
              <div className="small muted" style={{ marginTop: 6 }}>{t('urssaf.to_declare_hint')}</div>
            </div>
            <div className="stack" style={{ minWidth: 240 }}>
              <div className="row between small"><span className="muted">{t('urssaf.contributions_est')}</span><span className="mono" style={{ fontWeight: 600 }}>{money(next.contributions, language)}</span></div>
              <div className="row between small"><span className="muted">{t('urssaf.deadline')}</span><span>{date(next.deadline, language, 'long')}</span></div>
              <div className="row between small"><span className="muted" /> <span className="xsmall muted">{daysFromNow(next.deadline, language)}</span></div>
              <div className="row wrap" style={{ marginTop: 4 }}>
                <a className="btn sm" href="https://autoentrepreneur.urssaf.fr" target="_blank" rel="noreferrer"><ExternalLink size={14} /> {t('urssaf.go_declare')}</a>
                {next.status !== 'in_progress' && (
                  <button className="btn sm dark" disabled={busy === next.key} onClick={() => declare(next, true)}>
                    {busy === next.key ? <Spinner /> : <CircleCheck size={14} />} {t('urssaf.mark_declared')}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-4">
        <StatCard icon={Wallet} label={t('urssaf.ca_year')} value={money(data?.ca_year, language)} loading={!data} foot={t('urssaf.ca_year_foot')} />
        <StatCard icon={Landmark} label={t('urssaf.contributions')} value={money(data?.contributions_year, language)} loading={!data}
          foot={data ? t('urssaf.rate', { rate: percent(data.activity.total_rate, language, 1) }) : ''} />
        <StatCard icon={PiggyBank} label={t('urssaf.net')} value={money(data?.net_year, language)} loading={!data} foot={t('urssaf.net_foot')} />
        <StatCard icon={HandCoins} label={t('urssaf.pending')} value={money(data?.pending_ht, language)} loading={!data} foot={t('urssaf.pending_foot')} />
      </div>

      <div className="grid grid-main section-gap">
        <div className="card">
          <div className="card-head">
            <div className="card-title"><BarChart3 size={16} /> {t('urssaf.chart')}</div>
            <span className="small muted">{year}</span>
          </div>
          {data ? <BarsChart data={data.monthly} xKey="month" title={t('urssaf.chart')}
            series={[{ key: 'ca', label: t('urssaf.ca_short'), color: 'var(--series-collected)' }]} /> : <div className="skeleton" style={{ height: 260 }} />}
        </div>
        <div className="stack lg">
          <div className="card">
            <div className="card-head"><div className="card-title"><Gauge size={16} /> {t('urssaf.thresholds')}</div></div>
            {data && (
              <div className="stack lg">
                <Threshold label={t('urssaf.plafond')} value={data.ca_year} limit={data.thresholds.plafond} ratio={data.thresholds.plafond_ratio} language={language} />
                <Threshold label={t('urssaf.franchise')} value={data.ca_year} limit={data.thresholds.franchise_tva} ratio={data.thresholds.franchise_ratio} language={language} />
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-head"><div className="card-title"><Info size={16} /> {t('urssaf.regime')}</div></div>
            {data && (
              <div className="stack sm small">
                <div style={{ fontWeight: 600 }}>{t(`activity.${data.activity.key}`)}</div>
                <div className="row between"><span className="muted">{t('urssaf.social')}</span><span className="mono">{percent(data.activity.rate, language, 1)}</span></div>
                <div className="row between"><span className="muted">{t('urssaf.cfp')}</span><span className="mono">{percent(data.activity.cfp, language, 1)}</span></div>
                {data.activity.versement_liberatoire && <div className="row between"><span className="muted">{t('urssaf.vl')}</span><span className="mono">{percent(data.activity.vl, language, 1)}</span></div>}
                <div className="row between"><span className="muted">{t('urssaf.frequency')}</span><span>{t(`settings.${data.frequency}`)}</span></div>
                <button className="link" style={{ marginTop: 6 }} onClick={() => openSettings('fiscal')}>{t('urssaf.change')}</button>
                <p className="xsmall subtle" style={{ marginTop: 6 }}>{t('urssaf.disclaimer')}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card flush section-gap">
        <div className="card-head" style={{ padding: '18px 20px 0' }}>
          <div className="card-title"><CalendarClock size={16} /> {t('urssaf.periods')}</div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>{t('urssaf.period')}</th><th className="right">{t('urssaf.ca_short')}</th><th className="right hide-mobile">{t('urssaf.contributions')}</th><th className="hide-mobile">{t('urssaf.deadline')}</th><th>{t('invoices.status')}</th><th /></tr>
            </thead>
            <tbody>
              {(data?.periods || []).map((p) => (
                <tr key={p.key}>
                  <td style={{ fontWeight: 550 }}>{p.label}</td>
                  <td className="right mono">{money(p.ca, language)}</td>
                  <td className="right mono small hide-mobile">{money(p.contributions, language)}</td>
                  <td className="small hide-mobile nowrap">{date(p.deadline, language)}</td>
                  <td><DeclarationStatus status={p.status} /></td>
                  <td className="right">
                    {['to_declare', 'late'].includes(p.status) && (
                      <button className="btn sm" disabled={busy === p.key} onClick={() => declare(p, true)}>{busy === p.key ? <Spinner /> : <CircleCheck size={14} />}<span className="hide-mobile">{t('urssaf.declared_btn')}</span></button>
                    )}
                    {p.status === 'declared' && (
                      <button className="icon-btn" title={t('urssaf.undo')} aria-label={t('urssaf.undo')} disabled={busy === p.key} onClick={() => declare(p, false)}><Undo2 size={15} /></button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
