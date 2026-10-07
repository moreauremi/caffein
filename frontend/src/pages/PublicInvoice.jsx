// SPDX-License-Identifier: AGPL-3.0-or-later
import { useParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Download, FileText, Landmark } from 'lucide-react'
import Logo from '../components/Logo'
import { EmptyState, Spinner } from '../components/ui'
import { useLanguage } from '../context/LanguageContext'
import { date, money } from '../lib/format'
import { useApi } from '../lib/useApi'

// Page publique ouverte depuis le lien des emails (« Voir la facture & régler »).
// Pas de paiement en ligne : le client règle par virement avec les coordonnées affichées.
export default function PublicInvoice() {
  const { token } = useParams()
  const { t, language } = useLanguage()
  const { data, error, loading } = useApi(`/api/public/invoices/${token}`)

  if (loading) return <div className="container page"><Spinner /></div>
  if (error || !data) return <div className="container page"><EmptyState icon={FileText} title={t('public.not_found')} /></div>

  const { invoice: inv, issuer, client } = data
  const isQuote = inv.kind === 'quote'
  const paid = inv.display_status === 'paid'
  const overdue = inv.display_status === 'overdue'
  return (
    <div className="container page" style={{ maxWidth: 760 }}>
      <div className="row between" style={{ marginBottom: 28 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 20 }}>{issuer.company || issuer.full_name}</div>
          <div className="small muted">{issuer.email}</div>
        </div>
        <span className="row xsmall muted" style={{ gap: 6 }}>{t('public.powered')} <Logo size={18} /></span>
      </div>

      <div className="card" style={{ padding: 28 }}>
        <div className="row between wrap" style={{ gap: 16 }}>
          <div>
            <div className="small muted">{isQuote ? t('public.quote_for') : t('public.invoice_for')} {client.name}</div>
            <div className="mono" style={{ fontWeight: 600, marginTop: 4 }}>{inv.number}</div>
            {inv.title && <div className="small" style={{ marginTop: 4 }}>{inv.title}</div>}
          </div>
          {paid ? <span className="badge good"><CheckCircle2 /> {t('public.paid', { date: date(inv.paid_at, language, 'long') })}</span>
            : overdue ? <span className="badge bad"><AlertTriangle /> {t('public.overdue')}</span>
              : <span className="badge info">{isQuote ? t('public.valid_until', { date: date(inv.due_date, language, 'long') }) : t('public.due', { date: date(inv.due_date, language, 'long') })}</span>}
        </div>
        <div className="amount-big" style={{ fontSize: 44, margin: '24px 0 6px' }}>{money(inv.total, language)}</div>
        <div className="small muted">{inv.vat_exempt ? t('public.vat_exempt') : t('public.incl_vat', { vat: money(inv.vat_amount, language) })}</div>

        <table className="table" style={{ marginTop: 22 }}>
          <tbody>
            {inv.items.map((it, i) => (
              <tr key={i}>
                <td>{it.description}{it.quantity !== 1 && <span className="muted"> × {it.quantity}</span>}</td>
                <td className="right mono">{money(it.quantity * it.unit_price, language)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="row wrap" style={{ marginTop: 22 }}>
          <a className="btn primary" href={`/api/public/invoices/${token}/pdf?download=1`}><Download size={16} /> {t('public.download')}</a>
          <a className="btn" href={`/api/public/invoices/${token}/pdf`} target="_blank" rel="noreferrer"><FileText size={16} /> {t('public.view')}</a>
        </div>
      </div>

      {!isQuote && !paid && issuer.iban && (
        <div className="card section-gap">
          <div className="card-title" style={{ marginBottom: 14 }}><Landmark size={16} /> {t('public.transfer')}</div>
          <div className="stack sm small">
            <div className="row between wrap"><span className="muted">{t('public.beneficiary')}</span><span style={{ fontWeight: 600 }}>{issuer.company || issuer.full_name}</span></div>
            <div className="row between wrap"><span className="muted">IBAN</span><span className="mono">{issuer.iban}</span></div>
            {issuer.bic && <div className="row between wrap"><span className="muted">BIC</span><span className="mono">{issuer.bic}</span></div>}
            <div className="row between wrap"><span className="muted">{t('public.reference')}</span><span className="mono">{inv.number}</span></div>
          </div>
        </div>
      )}
      <p className="xsmall subtle" style={{ marginTop: 18, textAlign: 'center' }}>
        {issuer.company || issuer.full_name}{issuer.siret ? ` — SIRET ${issuer.siret}` : ''}{issuer.address ? ` — ${issuer.address}, ${issuer.zip_code} ${issuer.city}` : ''}
      </p>
    </div>
  )
}
