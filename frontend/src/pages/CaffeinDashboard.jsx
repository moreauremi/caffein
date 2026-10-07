// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, BarChart3, CalendarClock, Clock3, FileCheck2, FileSignature, FileStack, FolderOpen, Inbox, Info, Landmark,
  Percent, Receipt, Send,
} from 'lucide-react'
import { BarsChart } from '../components/charts'
import DropZone from '../components/DropZone'
import FolderModal from '../components/FolderModal'
import { EmptyState, Segmented, StatCard, TvaType } from '../components/ui'
import { useLanguage } from '../context/LanguageContext'
import { capitalize, date, daysFromNow, duration, money, percent } from '../lib/format'
import { useApi } from '../lib/useApi'

const QUICK_FOLDERS = [
  { key: 'envoyees', icon: Send },
  { key: 'recues', icon: Receipt },
  { key: 'contrats', icon: FileSignature },
  { key: 'recus', icon: FileCheck2 },
]

function periodLabel(period, language) {
  if (!period) return ''
  if (period.key === 'year') return period.start.slice(0, 4)
  if (period.key === 'month') return date(period.start, language, 'month')
  const fmt = new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'fr-FR', { month: 'long' })
  const [y, m] = period.end.split('-').map(Number)
  const start = new Date(Number(period.start.slice(0, 4)), Number(period.start.slice(5, 7)) - 1, 1)
  return `${fmt.format(start)} – ${fmt.format(new Date(y, m - 1, 1))} ${y}`
}

export default function CaffeinDashboard() {
  const { t, language } = useLanguage()
  const [period, setPeriod] = useState('month')
  const [folder, setFolder] = useState(null)
  const { data, loading, reload } = useApi(`/api/tva?period=${period}`)
  const m = data?.metrics

  const series = [
    { key: 'collected', label: t('tva.collected'), color: 'var(--series-collected)' },
    { key: 'deductible', label: t('tva.deductible'), color: 'var(--series-deductible)' },
  ]
  const balancePositive = m?.balance > 0
  const ratio = Math.min(1, m?.ratio || 0)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('tva.title')}</h1>
          <p className="page-sub">
            {t('tva.subtitle')} <span style={{ color: 'var(--fg)', fontWeight: 600 }}>{capitalize(periodLabel(data?.period, language))}</span>
          </p>
        </div>
        <Segmented value={period} onChange={setPeriod} label={t('tva.period')}
          options={[{ value: 'month', label: t('tva.month') }, { value: 'quarter', label: t('tva.quarter') }, { value: 'year', label: t('tva.year') }]} />
      </div>

      {data?.vat_exempt && (
        <div className="alert info" style={{ marginBottom: 18 }}>
          <Info size={18} /><span>{t('tva.exempt_banner')}</span>
        </div>
      )}

      <div className="grid grid-4">
        <StatCard icon={FileStack} label={t('tva.card_documents')} value={m?.documents ?? '—'} loading={loading} foot={t('tva.card_documents_foot')} />
        <StatCard icon={Clock3} label={t('tva.card_time')} value={duration(m?.time_saved_min, language)} loading={loading} foot={t('tva.card_time_foot')} />
        <StatCard icon={Percent} label={t('tva.collected')} value={money(m?.collected, language)} loading={loading}
          foot={t('tva.on_sales', { amount: money(m?.ht_sales, language, { decimals: 0 }) })} />
        <StatCard icon={Landmark} label={t('tva.balance')} value={money(m?.balance, language)} loading={loading} dark={balancePositive}
          foot={balancePositive ? t('tva.balance_due') : t('tva.balance_credit')} />
      </div>

      <div className="grid grid-main section-gap">
        <div className="stack lg">
          <div className="card">
            <div className="card-head">
              <div className="card-title"><Percent size={16} /> {t('tva.tracking')}</div>
              {data?.deadline && (
                <span className={`badge ${data.deadline.days_left <= 7 ? 'warn' : 'outline'}`}>
                  <CalendarClock /> {t('tva.deadline', { date: date(data.deadline.date, language, 'long'), rel: daysFromNow(data.deadline.date, language) })}
                </span>
              )}
            </div>
            <div className="grid grid-2" style={{ gap: 12 }}>
              {[['collected', m?.collected, t('tva.collected_hint')], ['deductible', m?.deductible, t('tva.deductible_hint')]].map(([key, value, hint]) => (
                <div key={key} className="card tight" style={{ boxShadow: 'none', background: 'var(--surface-2)' }}>
                  <div className="row small muted" style={{ gap: 8 }}>
                    <span className="key" style={{ background: `var(--series-${key})` }} />{t(`tva.${key}`)}
                  </div>
                  <div className="mono" style={{ fontSize: 24, marginTop: 6, letterSpacing: '-0.03em' }}>{money(value, language)}</div>
                  <div className="xsmall muted" style={{ marginTop: 2 }}>{hint}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 18 }}>
              <div className="row between small" style={{ marginBottom: 8 }}>
                <span className="muted">{t('tva.ratio')}</span>
                <span className="mono">{percent(m?.ratio || 0, language)}</span>
              </div>
              <div className="progress" role="progressbar" aria-valuenow={Math.round(ratio * 100)} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${ratio * 100}%`, background: 'var(--series-deductible)' }} />
              </div>
            </div>
            <hr className="divider" />
            <div className="row between wrap">
              <div>
                <div className="small muted">{t('tva.net')}</div>
                <div className="amount-big" style={{ marginTop: 6 }}>{money(m?.balance, language)}</div>
              </div>
              <div className="small muted" style={{ maxWidth: 300 }}>
                {balancePositive ? t('tva.net_due_text') : t('tva.net_credit_text')}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div className="card-title"><BarChart3 size={16} /> {t('tva.evolution')}</div>
              <span className="small muted">{t(`tva.chart_${period}`)}</span>
            </div>
            {data && <BarsChart data={data.chart} xKey="period" series={series} title={t('tva.evolution')} />}
            {!data && <div className="skeleton" style={{ height: 260 }} />}
          </div>
        </div>

        <div className="stack lg">
          <div className="card">
            <div className="card-head"><div className="card-title"><Inbox size={16} /> {t('tva.drop_title')}</div></div>
            <DropZone compact onDone={reload} />
          </div>
          <div className="card">
            <div className="card-head"><div className="card-title"><FolderOpen size={16} /> {t('tva.quick_access')}</div></div>
            <div className="grid grid-2" style={{ gap: 8 }}>
              {QUICK_FOLDERS.map(({ key, icon: Icon }) => (
                <button key={key} className="btn" style={{ height: 'auto', padding: '12px', flexDirection: 'column', gap: 6 }} onClick={() => setFolder(key)}>
                  <Icon size={18} style={{ color: 'var(--accent)' }} />
                  <span className="small">{t(`folders.${key}`)}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="card flush section-gap">
        <div className="card-head" style={{ padding: '18px 20px 0' }}>
          <div className="card-title"><FileStack size={16} /> {t('tva.recent')}</div>
          <Link to="/documents" className="link small">{t('common.see_all')} <ArrowRight size={14} /></Link>
        </div>
        {data?.recent?.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('docs.type')}</th><th>{t('docs.supplier')}</th><th className="hide-mobile">{t('docs.category')}</th>
                  <th className="right hide-mobile">HT</th><th className="right hide-mobile">TVA</th><th className="right">TTC</th><th className="right">{t('docs.date')}</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((d) => (
                  <tr key={d.id}>
                    <td><TvaType type={d.tva_type} /></td>
                    <td>
                      <div style={{ fontWeight: 600 }} className="truncate">{d.fournisseur}</div>
                      <div className="xsmall muted truncate" style={{ maxWidth: 300 }}>{d.resume}</div>
                    </td>
                    <td className="hide-mobile small">{d.categorie}</td>
                    <td className="right mono small hide-mobile">{money(d.ht, language)}</td>
                    <td className="right mono small hide-mobile">{money(d.tva, language)}</td>
                    <td className="right mono">{money(d.ttc, language)}</td>
                    <td className="right small muted nowrap">{date(d.date, language)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon={FileStack} title={t('docs.empty')} />}
      </div>

      {folder && <FolderModal folderKey={folder} onClose={() => setFolder(null)} />}
    </div>
  )
}
