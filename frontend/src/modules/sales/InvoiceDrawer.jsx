// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import {
  BellRing, Ban, Check, CheckCircle2, Download, FileOutput, Mail, Plus, Save, Send, Sparkles, Trash2, X,
} from 'lucide-react'
import { useApp } from '../../context/AppContext'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { date, money, relative, todayIso } from '../../lib/format'
import { useDebounced } from '../../lib/useDebounced'
import ClientModal from './ClientModal'
import { ConfirmButton, Drawer, EmailStatus, InvoiceStatus, ReminderDots, Spinner, Toggle } from '../../components/ui'

const VAT_RATES = [0.2, 0.1, 0.055, 0.021]
const blankItem = () => ({ description: '', quantity: 1, unit_price: 0 })


function draftFrom(inv, profile, kind) {
  return {
    kind: inv?.kind || kind,
    client_id: inv?.client_id ?? '',
    title: inv?.title || '',
    items: inv?.items?.length ? inv.items : [blankItem()],
    vat_exempt: inv ? inv.vat_exempt : Boolean(profile?.vat_exempt),
    vat_rate: inv ? inv.vat_rate : profile?.default_vat_rate ?? 0.2,
    issued_at: inv?.issued_at || '',
    due_date: inv?.due_date || '',
    delivery_date: inv?.delivery_date || '',
    payment_conditions: inv?.payment_conditions || '',
    notes: inv?.notes || '',
  }
}

export default function InvoiceDrawer({ invoiceId, kind = 'invoice', onClose, onChanged, origin }) {
  const { t, language } = useLanguage()
  const { profile } = useApp()
  const toast = useToast()
  const [invoice, setInvoice] = useState(null)
  const [form, setForm] = useState(() => draftFrom(null, profile, kind))
  const [clients, setClients] = useState([])
  const [clientModal, setClientModal] = useState(false)
  const [busy, setBusy] = useState('')
  const [paidAt, setPaidAt] = useState(todayIso())
  const [id, setId] = useState(invoiceId)

  useEffect(() => {
    api.get('/api/clients').then(setClients).catch(() => {})
  }, [])

  useEffect(() => {
    if (!id) return
    api.get(`/api/invoices/${id}`).then((inv) => {
      setInvoice(inv)
      setForm(draftFrom(inv, profile, kind))
    }).catch((err) => toast(err.message, 'error'))
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  const isDraft = !invoice || invoice.status === 'draft'
  const docKind = invoice?.kind || form.kind
  const isQuote = docKind === 'quote'
  // Totaux calculés par le serveur pendant la saisie (les mêmes règles que pour l'enregistrement)
  const totalsQuery = useDebounced(JSON.stringify({ items: form.items, vat_exempt: form.vat_exempt, vat_rate: form.vat_rate }), 250)
  const [sums, setSums] = useState({ subtotal: 0, vat_amount: 0, total: 0, lines: [] })
  useEffect(() => {
    let cancelled = false
    api.post('/api/invoices/preview', JSON.parse(totalsQuery))
      .then((result) => !cancelled && setSums(result))
      .catch(() => {})
    return () => { cancelled = true }
  }, [totalsQuery])

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }))
  const setItem = (index, key, value) => setForm((f) => ({ ...f, items: f.items.map((it, i) => (i === index ? { ...it, [key]: value } : it)) }))

  function changed(inv, message) {
    setInvoice(inv)
    setForm(draftFrom(inv, profile, kind))
    onChanged?.(inv)
    if (message) toast(message)
  }

  async function run(label, fn) {
    setBusy(label)
    try {
      return await fn()
    } catch (err) {
      toast(err.message, 'error')
      return null
    } finally {
      setBusy('')
    }
  }

  async function saveDraft({ quiet = false } = {}) {
    const payload = {
      ...form,
      client_id: form.client_id === '' ? null : Number(form.client_id),
      items: form.items.filter((i) => i.description.trim()).map((i) => ({ ...i, quantity: Number(i.quantity), unit_price: Number(i.unit_price) })),
      vat_rate: Number(form.vat_rate),
    }
    const inv = id ? await api.put(`/api/invoices/${id}`, payload) : await api.post('/api/invoices', payload)
    if (!id) setId(inv.id)
    changed(inv, quiet ? null : t('invoices.saved'))
    return inv
  }

  const save = () => run('save', () => saveDraft())
  const preview = () => run('pdf', async () => {
    const inv = await saveDraft({ quiet: true })
    window.open(`/api/invoices/${inv.id}/pdf`, '_blank', 'noopener')
  })
  const finalize = () => run('finalize', async () => {
    const draft = await saveDraft({ quiet: true })
    changed(await api.post(`/api/invoices/${draft.id}/finalize`), t(isQuote ? 'invoices.quote_issued' : 'invoices.issued'))
  })
  const send = () => run('send', async () => {
    const target = isDraft ? await saveDraft({ quiet: true }) : invoice
    const { run: result, invoice: inv } = await api.post(`/api/invoices/${target.id}/send`)
    changed(inv)
    toast(result.summary, result.status === 'error' ? 'error' : 'success')
  })
  const markPaid = () => run('paid', async () => changed(await api.post(`/api/invoices/${id}/paid`, { paid_at: paidAt }), t('invoices.marked_paid')))
  const remind = () => run('remind', async () => {
    const { run: result, invoice: inv } = await api.post(`/api/invoices/${id}/remind`)
    changed(inv)
    toast(result.summary, result.status === 'error' ? 'error' : 'success')
  })
  const cancel = () => run('cancel', async () => changed(await api.post(`/api/invoices/${id}/cancel`), t('invoices.cancelled')))
  const quoteStatus = (status) => run(status, async () => changed(await api.post(`/api/invoices/${id}/quote-status`, { status })))
  const convert = () => run('convert', async () => {
    const inv = await api.post(`/api/invoices/${id}/convert`)
    toast(t('invoices.converted'))
    onChanged?.(inv)
    setInvoice(null)
    setId(inv.id)
  })
  const remove = async () => {
    await api.del(`/api/invoices/${id}`)
    toast(t('invoices.deleted'))
    onChanged?.(null)
    onClose()
  }

  const title = invoice?.number || (isQuote ? t('invoices.new_quote') : t('invoices.new_invoice'))
  const status = invoice?.display_status
  const action = (name, label, onClick, cls = 'btn') => (
    <button key={name} className={cls} onClick={onClick} disabled={Boolean(busy)}>{busy === name ? <Spinner /> : null}{label}</button>
  )

  const footer = isDraft ? (
    <>
      {id && <ConfirmButton className="btn danger" confirmLabel={t('common.confirm_delete')} onConfirm={remove}><Trash2 size={15} /></ConfirmButton>}
      <span className="grow" />
      {action('pdf', <><FileOutput size={16} /> {t('invoices.preview')}</>, preview)}
      {action('save', <><Save size={16} /> {t('common.save')}</>, save)}
      {action('finalize', <><Check size={16} /> {t('invoices.issue')}</>, finalize)}
      {action('send', <><Send size={16} /> {t('invoices.issue_send')}</>, send, 'btn primary')}
    </>
  ) : (
    <>
      <a className="btn" href={`/api/invoices/${id}/pdf?download=1`}><Download size={16} /> PDF</a>
      <span className="grow" />
      {!isQuote && ['pending', 'overdue'].includes(status) && (
        <>
          {status === 'overdue' && action('remind', <><BellRing size={16} /> {t('invoices.remind')}</>, remind)}
          {action('send', <><Mail size={16} /> {invoice?.emailed_at ? t('invoices.resend') : t('invoices.send')}</>, send)}
        </>
      )}
      {isQuote && ['pending', 'accepted'].includes(status) && (
        <>
          {status === 'pending' && action('send', <><Mail size={16} /> {invoice?.emailed_at ? t('invoices.resend') : t('invoices.send')}</>, send)}
          {status === 'pending' && action('refused', <><X size={16} /> {t('invoices.refuse')}</>, () => quoteStatus('refused'))}
          {status === 'pending' && action('accepted', <><Check size={16} /> {t('invoices.accept')}</>, () => quoteStatus('accepted'))}
          {action('convert', <><Sparkles size={16} /> {t('invoices.convert')}</>, convert, 'btn primary')}
        </>
      )}
    </>
  )

  return (
    <Drawer title={title} onClose={onClose} footer={footer}
      subtitle={invoice ? <span className="row" style={{ gap: 8 }}><InvoiceStatus status={status} kind={docKind} />{invoice.client_name}</span> : t(isQuote ? 'invoices.quote_draft_hint' : 'invoices.draft_hint')}>
      {origin && isDraft && (
        <div className="alert info small" style={{ marginBottom: 18 }}>
          <Sparkles size={16} />
          <span>{t(origin.parsed_by === 'claude' ? 'invoices.from_ai_claude' : 'invoices.from_ai_local')}{origin.created_client ? ` ${t('invoices.client_created')}` : ''}</span>
        </div>
      )}
      {invoice?.source_text && isDraft && (
        <div className="code" style={{ marginBottom: 18, whiteSpace: 'normal' }}>« {invoice.source_text} »</div>
      )}

      {isDraft ? (
        <div className="stack lg">
          <div className="form-grid">
            <div className="field full">
              <label htmlFor="inv-client">{t('invoices.client')}</label>
              <div className="row">
                <select id="inv-client" className="select grow" value={form.client_id ?? ''} onChange={(e) => set('client_id', e.target.value)}>
                  <option value="">{t('invoices.choose_client')}</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}{c.contact_name && c.contact_name !== c.name ? ` — ${c.contact_name}` : ''}</option>)}
                </select>
                <button className="btn" onClick={() => setClientModal(true)}><Plus size={16} /> {t('clients.new_short')}</button>
              </div>
            </div>
            <div className="field full">
              <label htmlFor="inv-title">{t('invoices.object')}</label>
              <input id="inv-title" className="input" value={form.title} placeholder={t('invoices.object_ph')} onChange={(e) => set('title', e.target.value)} />
            </div>
          </div>

          <div>
            <div className="label" style={{ marginBottom: 8 }}>{t('invoices.lines')}</div>
            <div className="stack sm">
              {form.items.map((item, i) => (
                <div key={i} className="card tight" style={{ boxShadow: 'none', padding: 12 }}>
                  <div className="row" style={{ alignItems: 'flex-start' }}>
                    <textarea className="textarea grow" rows={1} style={{ minHeight: 40 }} value={item.description}
                      placeholder={t('invoices.line_ph')} aria-label={t('invoices.description')}
                      onChange={(e) => setItem(i, 'description', e.target.value)} />
                    <button className="icon-btn" aria-label={t('common.delete')} disabled={form.items.length === 1}
                      onClick={() => set('items', form.items.filter((_, j) => j !== i))}><Trash2 size={16} /></button>
                  </div>
                  <div className="row wrap" style={{ marginTop: 8 }}>
                    <label className="row small muted" style={{ gap: 6 }}>{t('invoices.qty')}
                      <input className="input sm num mono" style={{ width: 80 }} type="number" min="0" step="0.5" value={item.quantity}
                        onChange={(e) => setItem(i, 'quantity', e.target.value)} />
                    </label>
                    <label className="row small muted" style={{ gap: 6 }}>{t('invoices.unit_price')}
                      <input className="input sm num mono" style={{ width: 120 }} type="number" min="0" step="10" value={item.unit_price}
                        onChange={(e) => setItem(i, 'unit_price', e.target.value)} />
                    </label>
                    <span className="grow" />
                    <span className="mono small">{money(sums.lines[i] ?? 0, language)}</span>
                  </div>
                </div>
              ))}
            </div>
            <button className="btn sm ghost" style={{ marginTop: 8 }} onClick={() => set('items', [...form.items, blankItem()])}>
              <Plus size={15} /> {t('invoices.add_line')}
            </button>
          </div>

          <div className="card tight" style={{ boxShadow: 'none' }}>
            <div className="row between">
              <div>
                <div style={{ fontWeight: 600 }}>{t('invoices.vat_exempt')}</div>
                <div className="xsmall muted">{t('invoices.vat_exempt_hint')}</div>
              </div>
              <Toggle checked={form.vat_exempt} onChange={(v) => set('vat_exempt', v)} label={t('invoices.vat_exempt')} />
            </div>
            {!form.vat_exempt && (
              <div className="row" style={{ marginTop: 12 }}>
                <span className="small muted">{t('invoices.vat_rate')}</span>
                <select className="select sm" style={{ width: 110 }} value={form.vat_rate} onChange={(e) => set('vat_rate', Number(e.target.value))}>
                  {VAT_RATES.map((r) => <option key={r} value={r}>{(r * 100).toLocaleString(language)} %</option>)}
                </select>
              </div>
            )}
            <hr className="divider" style={{ margin: '14px 0' }} />
            <div className="stack sm small">
              <div className="row between"><span className="muted">{t('invoices.subtotal')}</span><span className="mono">{money(sums.subtotal, language)}</span></div>
              <div className="row between"><span className="muted">TVA</span><span className="mono">{form.vat_exempt ? t('invoices.not_applicable') : money(sums.vat_amount, language)}</span></div>
              <div className="row between" style={{ fontSize: 16, fontWeight: 650 }}><span>{form.vat_exempt ? 'Total' : 'Total TTC'}</span><span className="mono">{money(sums.total, language)}</span></div>
            </div>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="inv-issued">{t('invoices.issue_date')}</label>
              <input id="inv-issued" className="input" type="date" value={form.issued_at || ''} onChange={(e) => set('issued_at', e.target.value)} />
              <span className="hint">{t('invoices.issue_date_hint')}</span>
            </div>
            <div className="field">
              <label htmlFor="inv-due">{isQuote ? t('invoices.validity') : t('invoices.due_date')}</label>
              <input id="inv-due" className="input" type="date" value={form.due_date || ''} onChange={(e) => set('due_date', e.target.value)} />
              <span className="hint">{isQuote ? t('invoices.validity_hint') : t('invoices.due_hint', { n: profile?.payment_terms_days ?? 30 })}</span>
            </div>
            <div className="field">
              <label htmlFor="inv-delivery">{t('invoices.delivery')}</label>
              <input id="inv-delivery" className="input" type="date" value={form.delivery_date || ''} onChange={(e) => set('delivery_date', e.target.value)} />
            </div>
            {!isQuote && (
              <div className="field">
                <label htmlFor="inv-terms">{t('invoices.payment')}</label>
                <input id="inv-terms" className="input" value={form.payment_conditions} onChange={(e) => set('payment_conditions', e.target.value)} />
              </div>
            )}
            <div className="field full">
              <label htmlFor="inv-notes">{t('invoices.notes')}</label>
              <textarea id="inv-notes" className="textarea" rows={2} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
            </div>
          </div>
        </div>
      ) : invoice && (
        <div className="stack lg">
          <div className="grid grid-2" style={{ gap: 12 }}>
            <div className="card tight" style={{ boxShadow: 'none', background: 'var(--surface-2)' }}>
              <div className="small muted">{invoice.vat_exempt ? 'Total' : 'Total TTC'}</div>
              <div className="amount-big" style={{ fontSize: 30, marginTop: 6 }}>{money(invoice.total, language)}</div>
              <div className="xsmall muted" style={{ marginTop: 6 }}>HT {money(invoice.subtotal, language)} · TVA {money(invoice.vat_amount, language)}</div>
            </div>
            <div className="card tight" style={{ boxShadow: 'none', background: 'var(--surface-2)' }}>
              <div className="stack sm small">
                <div className="row between"><span className="muted">{t('invoices.issue_date')}</span><span>{date(invoice.issued_at, language)}</span></div>
                <div className="row between"><span className="muted">{isQuote ? t('invoices.validity') : t('invoices.due_date')}</span><span>{date(invoice.due_date, language)}</span></div>
                {invoice.delivery_date && <div className="row between"><span className="muted">{t('invoices.delivery')}</span><span>{date(invoice.delivery_date, language)}</span></div>}
                {status === 'overdue' && <div className="row between" style={{ color: 'var(--bad)' }}><span>{t('invoices.late')}</span><span>{t('invoices.days', { n: invoice.days_overdue })}</span></div>}
              </div>
            </div>
          </div>

          {!isQuote && ['pending', 'overdue'].includes(status) && (
            <div className="card tight row wrap" style={{ boxShadow: 'none' }}>
              <CheckCircle2 size={18} style={{ color: 'var(--good)' }} />
              <span className="small grow" style={{ fontWeight: 600 }}>{t('invoices.payment_received')}</span>
              <input className="input sm" type="date" style={{ width: 160 }} value={paidAt} onChange={(e) => setPaidAt(e.target.value)} aria-label={t('invoices.paid_on')} />
              {action('paid', <>{t('invoices.mark_paid')}</>, markPaid, 'btn sm dark')}
            </div>
          )}

          <div>
            <div className="label" style={{ marginBottom: 8 }}>{invoice.title || t('invoices.lines')}</div>
            <div className="card flush" style={{ boxShadow: 'none' }}>
              <table className="table">
                <thead><tr><th>{t('invoices.description')}</th><th className="right">{t('invoices.qty')}</th><th className="right">{t('invoices.unit_price')}</th><th className="right">Total HT</th></tr></thead>
                <tbody>
                  {invoice.items.map((it, i) => (
                    <tr key={i}>
                      <td>{it.description}</td>
                      <td className="right mono small">{it.quantity}</td>
                      <td className="right mono small">{money(it.unit_price, language)}</td>
                      <td className="right mono small">{money(it.amount, language)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <div className="label" style={{ marginBottom: 10 }}>{t('invoices.timeline')}</div>
            <div className="list">
              {[
                [t('invoices.tl_created'), invoice.created_at],
                [t(isQuote ? 'invoices.tl_quote_issued' : 'invoices.tl_issued'), invoice.issued_at],
                invoice.emailed_at && [t('invoices.tl_sent', { to: invoice.emailed_to }), invoice.emailed_at],
                invoice.reminder_count > 0 && [<span className="row" key="r" style={{ gap: 8 }}>{t('invoices.tl_reminders', { n: invoice.reminder_count })} <ReminderDots count={invoice.reminder_count} /></span>, invoice.last_reminder_at],
                invoice.paid_at && [t('invoices.tl_paid'), invoice.paid_at],
                status === 'cancelled' && [t('invoices.tl_cancelled'), invoice.updated_at],
              ].filter(Boolean).map(([label, when], i) => (
                <div className="list-item" key={i} style={{ padding: '9px 0' }}>
                  <span className="dot" style={{ background: 'var(--accent)' }} />
                  <span className="small grow">{label}</span>
                  <span className="xsmall muted nowrap">{date(when, language, 'medium')}</span>
                </div>
              ))}
            </div>
          </div>

          {invoice.emails?.length > 0 && (
            <div>
              <div className="label" style={{ marginBottom: 10 }}>{t('invoices.emails')}</div>
              <div className="list">
                {invoice.emails.map((e) => (
                  <a key={e.id} className="list-item" style={{ textDecoration: 'none', padding: '9px 0' }} href={`/api/emails/${e.id}/html`} target="_blank" rel="noreferrer">
                    <Mail size={16} className="muted" />
                    <span className="small grow truncate">{e.subject}</span>
                    <EmailStatus status={e.status} />
                    <span className="xsmall muted nowrap hide-mobile">{relative(e.created_at, language)}</span>
                  </a>
                ))}
              </div>
            </div>
          )}

          {!isQuote && ['pending', 'overdue', 'paid'].includes(status) && (
            <div className="row end">
              <ConfirmButton className="btn sm danger" confirmLabel={t('invoices.cancel_confirm')} onConfirm={cancel}>
                <Ban size={15} /> {t('invoices.cancel')}
              </ConfirmButton>
            </div>
          )}
        </div>
      )}

      {clientModal && (
        <ClientModal onClose={() => setClientModal(false)} onSaved={(c) => {
          setClients((list) => [...list, c].sort((a, b) => a.name.localeCompare(b.name)))
          set('client_id', c.id)
          setClientModal(false)
        }} />
      )}
    </Drawer>
  )
}
