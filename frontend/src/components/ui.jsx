// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle, Ban, Check, CheckCircle2, CircleDashed, Clock, FileClock, FilePen, Hourglass, Loader2, Send, X, XCircle,
} from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'

export function StatCard({ icon: Icon, label, value, foot, dark = false, loading = false }) {
  return (
    <div className={`card stat ${dark ? 'dark' : ''}`}>
      <div className="stat-label">
        {Icon && <span className="stat-icon"><Icon size={16} /></span>}
        {label}
      </div>
      {loading ? <div className="skeleton" style={{ height: 29, width: '70%' }} /> : <div className="stat-value">{value}</div>}
      {foot && <div className="stat-foot">{foot}</div>}
    </div>
  )
}

export function Spinner({ size = 16 }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
}

export function EmptyState({ icon: Icon = CircleDashed, title, children }) {
  return (
    <div className="empty">
      <div className="empty-icon"><Icon size={20} /></div>
      <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{title}</div>
      {children && <div className="small" style={{ marginTop: 4 }}>{children}</div>}
    </div>
  )
}

export function Toggle({ checked, onChange, label, id }) {
  return (
    <span className="toggle">
      <input id={id} type="checkbox" role="switch" checked={!!checked} aria-label={label}
        onChange={(e) => onChange(e.target.checked)} />
      <span />
    </span>
  )
}

export function Segmented({ value, options, onChange, label }) {
  return (
    <div className="segmented" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" aria-selected={value === o.value}
          className={value === o.value ? 'active' : ''} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function useEscape(onClose) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])
}

export function Modal({ title, onClose, children, footer, wide = false }) {
  useEscape(onClose)
  const { t } = useLanguage()
  // Portail dans <body> : un ancêtre animé (transform) ne doit pas devenir le bloc conteneur
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} />
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h3 style={{ fontSize: 17 }}>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label={t('common.close')}><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </>,
    document.body,
  )
}

export function Drawer({ title, subtitle, onClose, children, footer, narrow = false }) {
  useEscape(onClose)
  const { t } = useLanguage()
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} />
      <aside className={`drawer ${narrow ? 'narrow' : ''}`} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}>
        <div className="drawer-head">
          <div className="grow">
            <h3 style={{ fontSize: 18 }} className="truncate">{title}</h3>
            {subtitle && <div className="small muted" style={{ marginTop: 3 }}>{subtitle}</div>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label={t('common.close')}><X size={18} /></button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>,
    document.body,
  )
}

// Bouton à double confirmation (actions irréversibles)
export function ConfirmButton({ children, confirmLabel, onConfirm, className = 'btn danger', disabled }) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!armed) return undefined
    const timer = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer)
  }, [armed])
  return (
    <button type="button" className={`${className} ${armed ? 'solid' : ''}`} disabled={disabled || busy}
      onClick={async () => {
        if (!armed) return setArmed(true)
        setBusy(true)
        try {
          await onConfirm()
        } finally {
          setBusy(false)
          setArmed(false)
        }
      }}>
      {busy ? <Spinner /> : null}
      {armed ? confirmLabel : children}
    </button>
  )
}

// ── Statuts ──────────────────────────────────────────────────────────
const INVOICE_STATUS = {
  draft: { cls: '', icon: FilePen },
  pending: { cls: 'info', icon: Hourglass },
  overdue: { cls: 'bad', icon: AlertTriangle },
  paid: { cls: 'good', icon: CheckCircle2 },
  cancelled: { cls: 'outline', icon: Ban },
  accepted: { cls: 'good', icon: Check },
  refused: { cls: 'outline', icon: XCircle },
  invoiced: { cls: 'accent', icon: FileClock },
}

export function InvoiceStatus({ status, kind = 'invoice' }) {
  const { t } = useLanguage()
  const meta = INVOICE_STATUS[status] || INVOICE_STATUS.draft
  const Icon = meta.icon
  const label = kind === 'quote' && status === 'pending' ? t('status.quote_pending') : t(`status.${status}`)
  return <span className={`badge ${meta.cls}`}><Icon />{label}</span>
}

const RUN_STATUS = {
  success: { cls: 'good', icon: CheckCircle2 },
  warning: { cls: 'warn', icon: AlertTriangle },
  error: { cls: 'bad', icon: XCircle },
  running: { cls: 'info', icon: Loader2 },
}

export function RunStatus({ status }) {
  const { t } = useLanguage()
  const meta = RUN_STATUS[status] || RUN_STATUS.success
  const Icon = meta.icon
  return <span className={`badge ${meta.cls}`}><Icon />{t(`run.${status}`)}</span>
}

const DECL_STATUS = {
  declared: { cls: 'good', icon: CheckCircle2 },
  to_declare: { cls: 'warn', icon: Clock },
  late: { cls: 'bad', icon: AlertTriangle },
  in_progress: { cls: 'info', icon: Hourglass },
  upcoming: { cls: 'outline', icon: CircleDashed },
  untracked: { cls: 'outline', icon: Ban },
}

export function DeclarationStatus({ status }) {
  const { t } = useLanguage()
  const meta = DECL_STATUS[status] || DECL_STATUS.upcoming
  const Icon = meta.icon
  return <span className={`badge ${meta.cls}`}><Icon />{t(`decl.${status}`)}</span>
}

export function EmailStatus({ status }) {
  const { t } = useLanguage()
  const cls = { sent: 'good', simulated: 'info', failed: 'bad' }[status] || ''
  const Icon = { sent: Send, simulated: CircleDashed, failed: XCircle }[status] || Send
  return <span className={`badge ${cls}`}><Icon />{t(`email.${status}`)}</span>
}

export function TvaType({ type }) {
  const { t } = useLanguage()
  return (
    <span className="badge outline">
      <span className="key" style={{ background: type === 'collected' ? 'var(--series-collected)' : 'var(--series-deductible)' }} />
      {t(type === 'collected' ? 'tva.collected_short' : 'tva.deductible_short')}
    </span>
  )
}

export function ReminderDots({ count }) {
  const { t } = useLanguage()
  return (
    <span className="reminder-dots" title={t('invoices.reminders_count', { n: count })} aria-label={t('invoices.reminders_count', { n: count })}>
      {[0, 1, 2].map((i) => <i key={i} className={`${i < count ? 'on' : ''} ${i < count && i === 2 ? 'final' : ''}`} />)}
    </span>
  )
}
