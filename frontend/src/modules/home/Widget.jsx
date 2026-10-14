// SPDX-License-Identifier: AGPL-3.0-or-later
// Une carte de « Mes vues » : rendue à partir de sa description (source, visuel, paramètres)
// et des données calculées par le serveur. Aucun HTML venu de l'IA : seulement du texte.
import { Link } from 'react-router-dom'
import {
  AlertTriangle, CalendarClock, Clock3, FileSignature, Landmark, Percent, ReceiptText, TrendingUp, Wallet, X,
} from 'lucide-react'
import { BarsChart } from '../../components/charts'
import { EmptyState, InvoiceStatus, StatCard } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import { date, daysFromNow, duration, money } from '../../lib/format'

const METRIC_ICONS = {
  to_collect: Wallet, overdue_total: AlertTriangle, paid_month: ReceiptText, revenue_year: TrendingUp,
  quotes_pending: FileSignature, vat_balance: Percent, time_saved: Clock3,
}

// Couleurs des séries : palette des graphiques existants (validée pour le daltonisme)
const SERIES_COLORS = {
  invoiced: 'var(--series-collected)', paid: 'var(--series-deductible)', amount: 'var(--series-collected)',
  collected: 'var(--series-collected)', deductible: 'var(--series-deductible)',
}

// Titre affiché : celui choisi par l'IA, sinon un titre traduit selon la source et la période
function widgetTitle(widget, t) {
  if (widget.title) return widget.title
  if (widget.source === 'kpi') return t(`views.metric.${widget.params.metric}`)
  const base = t(`views.source.${widget.source}`)
  if (widget.source === 'unpaid_invoices' && widget.params.only_overdue) return t('views.source.overdue_invoices')
  return widget.params.period ? `${base} · ${t(`views.period.${widget.params.period}`)}` : base
}

function KpiWidget({ widget }) {
  const { t, language } = useLanguage()
  const { data, params } = widget
  const value = data.unit === 'minutes' ? duration(data.value, language) : money(data.value, language)
  const countKey = params.metric === 'quotes_pending' ? 'invoices.n_quotes' : 'views.kpi_count'
  const foot = data.vat_exempt ? t('views.vat_exempt')
    : data.count != null ? t(countKey, { n: data.count }) : t(`views.kpi_foot.${params.metric}`)
  return <StatCard icon={METRIC_ICONS[params.metric]} label={widgetTitle(widget, t)} value={value} foot={foot}
    dark={params.metric === 'overdue_total' && data.value > 0} />
}

function ChartWidget({ widget }) {
  const { t, language } = useLanguage()
  const { data } = widget
  if (!data.rows.length || data.rows.every((r) => data.series.every((s) => !r[s]))) {
    return <EmptyState icon={TrendingUp} title={t('views.no_data')} />
  }
  const series = data.series.map((key) => ({ key, label: t(`views.series.${key}`), color: SERIES_COLORS[key] }))
  const exempt = data.vat_exempt ? <p className="small muted" style={{ marginBottom: 12 }}>{t('views.vat_exempt')}</p> : null
  const xLabel = widget.source === 'revenue_by_client' ? t('views.col.client')
    : widget.source === 'expenses_by_category' ? t('views.col.category') : undefined
  if (widget.visual === 'table') {
    return (
      <div className="table-wrap">
        {exempt}
        <table className="table" aria-label={widgetTitle(widget, t)}>
          <thead><tr><th>{xLabel || t('chart.period')}</th>{series.map((s) => <th key={s.key} className="right">{s.label}</th>)}</tr></thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row[data.x]}>
                <td>{row[data.x]}</td>
                {series.map((s) => <td key={s.key} className="right mono">{money(row[s.key], language)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  return (
    <>
      {exempt}
      <BarsChart data={data.rows} xKey={data.x} series={series} height={240} title={widgetTitle(widget, t)} xLabel={xLabel} />
    </>
  )
}

function InvoicesWidget({ widget }) {
  const { t, language } = useLanguage()
  const { data, source } = widget
  if (!data.rows.length) return <EmptyState title={t(source === 'pending_quotes' ? 'views.no_quotes' : 'views.no_unpaid')} />
  const quotes = source === 'pending_quotes'
  return (
    <>
      <div className="table-wrap">
        <table className="table" aria-label={widgetTitle(widget, t)}>
          <thead>
            <tr>
              <th>{t('views.col.client')}</th>
              <th className="right">{t('views.col.total')}</th>
              <th>{quotes ? t('views.col.issued') : t('views.col.due')}</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.id}>
                <td style={{ maxWidth: 220 }}>
                  <div className="truncate">{row.client}</div>
                  <div className="xsmall muted mono truncate">{row.number}</div>
                </td>
                <td className="right mono">{money(row.total, language)}</td>
                <td>
                  {quotes ? date(row.issued_at, language) : (
                    row.status === 'overdue'
                      ? <span className="stack" style={{ gap: 3, alignItems: 'flex-start' }}><InvoiceStatus status="overdue" /><span className="xsmall muted">{t('views.days_late', { n: row.days_overdue })}</span></span>
                      : <span className="small">{date(row.due_date, language)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row between small muted" style={{ marginTop: 12 }}>
        <span>{t(quotes ? 'views.quotes_total' : 'views.unpaid_total', { n: data.count, amount: money(data.total, language) })}</span>
        <Link className="link small" to={quotes ? '/ventes/factures?tab=quote' : `/ventes/factures${widget.params.only_overdue ? '?status=overdue' : ''}`}>
          {t('common.see_all')}
        </Link>
      </div>
    </>
  )
}

function DeadlinesWidget({ widget }) {
  const { t, language } = useLanguage()
  if (!widget.data.rows.length) return <EmptyState icon={CalendarClock} title={t('home.no_deadline')} />
  return (
    <div className="list">
      {widget.data.rows.map((d) => (
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
  )
}

const BODIES = {
  revenue_by_month: ChartWidget, revenue_by_client: ChartWidget, expenses_by_category: ChartWidget, vat_by_month: ChartWidget,
  unpaid_invoices: InvoicesWidget, pending_quotes: InvoicesWidget, deadlines: DeadlinesWidget,
}

export default function Widget({ widget, onRemove, disabled = false }) {
  const { t } = useLanguage()
  const title = widgetTitle(widget, t)
  const remove = (
    <button type="button" className="icon-btn widget-remove" onClick={onRemove} disabled={disabled} aria-label={t('views.remove', { title })}
      title={t('views.remove', { title })}>
      <X size={16} />
    </button>
  )
  if (widget.source === 'kpi') {
    // Carte « En retard » inversée (fond sombre) : la croix suit la couleur de la carte
    const dark = widget.params.metric === 'overdue_total' && widget.data.value > 0
    return <div className={`widget widget-stat ${dark ? 'on-dark' : ''}`}>{remove}<KpiWidget widget={widget} /></div>
  }
  const Body = BODIES[widget.source]
  return (
    <section className={`card widget widget-${widget.visual}`} aria-label={title}>
      <div className="card-head">
        <h2 className="card-title">{title}</h2>
        {remove}
      </div>
      {Body ? <Body widget={widget} /> : null}
    </section>
  )
}
