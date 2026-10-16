// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, BellRing, CheckCircle2, FileOutput, FileText, Hourglass, Pencil, Plus, ReceiptText, Search, Send, Sparkles,
  Trash2, UsersRound, Wallet,
} from 'lucide-react'
import ClientModal from './ClientModal'
import InvoiceDrawer from './InvoiceDrawer'
import { EmptyState, InvoiceStatus, ReminderDots, Segmented, Spinner, StatCard } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { date, money } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const EXAMPLES = ['invoices.ex1', 'invoices.ex2', 'invoices.ex3']
const INVOICE_FILTERS = ['all', 'draft', 'pending', 'overdue', 'paid']
const QUOTE_FILTERS = ['all', 'draft', 'pending', 'accepted', 'refused', 'invoiced']

function AssistantBar({ onCreated }) {
  const { t } = useLanguage()
  const toast = useToast()
  const [text, setText] = useState('')
  const [kind, setKind] = useState('invoice')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e?.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true)
    try {
      const result = await api.post('/api/invoices/assistant', { text, kind })
      setText('')
      onCreated(result)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card accent-left" onSubmit={submit}>
      <div className="row between wrap" style={{ marginBottom: 12 }}>
        <div className="card-title"><Sparkles size={16} style={{ color: 'var(--accent)' }} /> {t('invoices.assistant_title')}</div>
        <Segmented value={kind} onChange={setKind} label={t('invoices.kind')}
          options={[{ value: 'invoice', label: t('invoices.invoice') }, { value: 'quote', label: t('invoices.quote') }]} />
      </div>
      <div className="row" style={{ alignItems: 'stretch' }}>
        <input className="input grow" style={{ height: 46, fontSize: 15 }} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={t('invoices.assistant_ph')} aria-label={t('invoices.assistant_title')} disabled={busy} />
        <button className="btn primary" style={{ height: 46 }} disabled={busy || !text.trim()}>
          {busy ? <Spinner /> : <Sparkles size={16} />}<span className="hide-mobile">{t('invoices.generate')}</span>
        </button>
      </div>
      <div className="chips" style={{ marginTop: 12 }}>
        {EXAMPLES.map((k) => (
          <button type="button" key={k} className="chip" onClick={() => setText(t(k))}>{t(k)}</button>
        ))}
      </div>
    </form>
  )
}

function ClientsTab({ clients, reload }) {
  const { t, language } = useLanguage()
  const toast = useToast()
  const [editing, setEditing] = useState(null)

  async function remove(c) {
    if (!window.confirm(t('clients.delete_confirm', { name: c.name }))) return
    try {
      await api.del(`/api/clients/${c.id}`)
      toast(t('clients.deleted'))
      reload()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  return (
    <div className="card flush">
      <div className="card-head" style={{ padding: '16px 20px 0' }}>
        <div className="card-sub">{t('clients.count', { n: clients.length })}</div>
        <button className="btn sm" onClick={() => setEditing({})}><Plus size={15} /> {t('clients.new')}</button>
      </div>
      {clients.length ? (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>{t('clients.f_name')}</th><th className="hide-mobile">{t('clients.f_email')}</th><th className="hide-mobile">{t('clients.f_city')}</th><th className="right">{t('clients.invoices')}</th><th className="right">{t('clients.paid')}</th><th /></tr></thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => setEditing(c)}>
                  <td><div style={{ fontWeight: 600 }}>{c.name}</div><div className="xsmall muted">{c.contact_name}</div></td>
                  <td className="small hide-mobile">{c.email || <span className="subtle">—</span>}</td>
                  <td className="small hide-mobile">{c.city}</td>
                  <td className="right mono small">{c.invoice_count}</td>
                  <td className="right mono small">{money(c.total_paid, language)}</td>
                  <td className="right" onClick={(e) => e.stopPropagation()}>
                    <div className="actions">
                      <button className="icon-btn" aria-label={t('common.edit')} onClick={() => setEditing(c)}><Pencil size={15} /></button>
                      <button className="icon-btn" aria-label={t('common.delete')} onClick={() => remove(c)}><Trash2 size={15} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState icon={UsersRound} title={t('clients.empty')} />}
      {editing && <ClientModal client={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}
    </div>
  )
}

export default function Invoices() {
  const { t, language } = useLanguage()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState(params.get('tab') || 'invoice')
  const [filter, setFilter] = useState(params.get('status') || 'all')
  const [query, setQuery] = useState('')
  // { id } | { kind } (nouveau document) + origin (résultat de l'assistant)
  const [drawer, setDrawer] = useState(() => (['invoice', 'quote'].includes(params.get('new')) ? { kind: params.get('new') } : null))
  const invoices = useApi('/api/invoices')
  const summary = useApi('/api/invoices/summary')
  const clients = useApi('/api/clients')

  useEffect(() => {
    if (params.has('new')) {
      params.delete('new')
      setParams(params, { replace: true })
    }
  }, [params, setParams])

  const reloadAll = () => { invoices.reload(); summary.reload(); clients.reload() }

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (invoices.data || []).filter((i) => i.kind === tab)
      .filter((i) => filter === 'all' || i.display_status === filter)
      .filter((i) => !q || [i.number, i.client_name, i.title].some((v) => (v || '').toLowerCase().includes(q)))
  }, [invoices.data, tab, filter, query])

  const counts = useMemo(() => {
    const all = invoices.data || []
    return { invoice: all.filter((i) => i.kind === 'invoice').length, quote: all.filter((i) => i.kind === 'quote').length }
  }, [invoices.data])

  async function quickAction(e, inv, path, message) {
    e.stopPropagation()
    try {
      const res = await api.post(`/api/invoices/${inv.id}/${path}`)
      toast(res.run ? res.run.summary : message, res.run?.status === 'error' ? 'error' : 'success')
      reloadAll()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const s = summary.data
  const filters = tab === 'quote' ? QUOTE_FILTERS : INVOICE_FILTERS
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('invoices.title')}</h1>
          <p className="page-sub">{t('invoices.subtitle')}</p>
        </div>
        <div className="row wrap">
          <button className="btn" onClick={() => setDrawer({ kind: 'quote' })}><FileText size={16} /> {t('invoices.new_quote')}</button>
          <button className="btn primary" onClick={() => setDrawer({ kind: 'invoice' })}><Plus size={16} /> {t('invoices.new_invoice')}</button>
        </div>
      </div>

      <AssistantBar onCreated={(result) => {
        reloadAll()
        setTab(result.invoice.kind)
        setDrawer({ id: result.invoice.id, origin: result })
      }} />

      <div className="grid grid-4 section-gap">
        <StatCard icon={Wallet} label={t('invoices.to_collect')} value={money(s?.to_collect, language)} loading={!s} foot={t('invoices.n_invoices', { n: s?.to_collect_count ?? 0 })} />
        <StatCard icon={AlertTriangle} label={t('invoices.overdue')} value={money(s?.overdue_total, language)} loading={!s} foot={t('invoices.overdue_foot', { n: s?.overdue_count ?? 0 })} />
        <StatCard icon={CheckCircle2} label={t('invoices.paid_month')} value={money(s?.paid_month, language)} loading={!s} foot={t('invoices.n_invoices', { n: s?.paid_month_count ?? 0 })} />
        <StatCard icon={Hourglass} label={t('invoices.quotes_pending')} value={money(s?.quotes_pending, language)} loading={!s} foot={t('invoices.n_quotes', { n: s?.quotes_pending_count ?? 0 })} />
      </div>

      <div className="section-gap">
        <div className="tabs" role="tablist">
          {[['invoice', ReceiptText, counts.invoice], ['quote', FileText, counts.quote], ['clients', UsersRound, clients.data?.length ?? 0]].map(([key, Icon, n]) => (
            <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''}
              onClick={() => { setTab(key); setFilter('all') }}>
              <Icon size={15} /> {t(`invoices.tab_${key}`)} <span className="count">{n}</span>
            </button>
          ))}
        </div>

        {tab === 'clients' ? <ClientsTab clients={clients.data || []} reload={clients.reload} /> : (
          <div className="card flush">
            <div className="row between wrap" style={{ padding: '14px 16px', gap: 12 }}>
              <div className="chips">
                {filters.map((f) => (
                  <button key={f} className={`chip ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
                    {f === 'all' ? t('invoices.filter_all') : t(tab === 'quote' && f === 'pending' ? 'status.quote_pending' : `status.${f}`)}
                  </button>
                ))}
              </div>
              <div className="input-icon" style={{ width: 240, maxWidth: '100%' }}>
                <Search size={16} />
                <input className="input sm" placeholder={t('common.search')} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t('common.search')} />
              </div>
            </div>
            {invoices.loading ? <div style={{ padding: 20 }}><div className="skeleton" style={{ height: 180 }} /></div> : list.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>N°</th><th>{t('invoices.client')}</th><th className="hide-mobile">{t('invoices.issue_date')}</th>
                      <th className="hide-mobile">{tab === 'quote' ? t('invoices.validity') : t('invoices.due_date')}</th>
                      <th className="right">{t('invoices.amount')}</th><th>{t('invoices.status')}</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((inv) => (
                      <tr key={inv.id} className="clickable" onClick={() => setDrawer({ id: inv.id })}>
                        <td className="mono small nowrap">{inv.number || <span className="subtle">{t('status.draft')}</span>}</td>
                        <td>
                          <div style={{ fontWeight: 600 }} className="truncate">{inv.client_name || <span className="subtle">—</span>}</div>
                          <div className="xsmall muted truncate" style={{ maxWidth: 260 }}>{inv.title}</div>
                        </td>
                        <td className="small hide-mobile nowrap">{date(inv.issued_at, language)}</td>
                        <td className="small hide-mobile nowrap">
                          {date(inv.due_date, language)}
                          {inv.display_status === 'overdue' && <div className="xsmall" style={{ color: 'var(--bad)' }}>{t('invoices.days_late', { n: inv.days_overdue })}</div>}
                        </td>
                        <td className="right mono nowrap">{money(inv.total, language)}</td>
                        <td>
                          <div className="row" style={{ gap: 8 }}>
                            <InvoiceStatus status={inv.display_status} kind={inv.kind} />
                            {inv.kind === 'invoice' && inv.reminder_count > 0 && <ReminderDots count={inv.reminder_count} />}
                          </div>
                        </td>
                        <td className="right" onClick={(e) => e.stopPropagation()}>
                          <div className="actions">
                            <a className="icon-btn" href={`/api/invoices/${inv.id}/pdf`} target="_blank" rel="noreferrer" aria-label={t('invoices.preview')} title={t('invoices.preview')}>
                              <FileOutput size={16} />
                            </a>
                            {inv.status === 'draft' && (
                              <button className="icon-btn" title={t('invoices.issue_send')} aria-label={t('invoices.issue_send')} onClick={(e) => quickAction(e, inv, 'send')}><Send size={16} /></button>
                            )}
                            {inv.display_status === 'overdue' && (
                              <button className="icon-btn" title={t('invoices.remind')} aria-label={t('invoices.remind')} onClick={(e) => quickAction(e, inv, 'remind')}><BellRing size={16} /></button>
                            )}
                            {inv.kind === 'invoice' && ['pending', 'overdue'].includes(inv.display_status) && (
                              <button className="icon-btn" title={t('invoices.mark_paid')} aria-label={t('invoices.mark_paid')} onClick={(e) => quickAction(e, inv, 'paid', t('invoices.marked_paid'))}><CheckCircle2 size={16} /></button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState icon={ReceiptText} title={t('invoices.empty')}>{t('invoices.empty_hint')}</EmptyState>}
          </div>
        )}
      </div>

      {drawer && (
        <InvoiceDrawer key={drawer.id || drawer.kind} invoiceId={drawer.id} kind={drawer.kind} origin={drawer.origin}
          onClose={() => setDrawer(null)} onChanged={reloadAll} />
      )}
    </div>
  )
}
