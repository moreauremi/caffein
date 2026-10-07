// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from 'react'
import {
  Bot, CalendarClock, Clock, Copy, History, Inbox, Mail, MailOpen, Paperclip, Play, Server, Sparkles, Terminal, Workflow,
} from 'lucide-react'
import { JOB_ICONS } from '../components/jobIcons'
import { EmailStatus, EmptyState, Modal, RunStatus, Spinner } from '../components/ui'
import { useLanguage } from '../context/LanguageContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'
import { date, relative } from '../lib/format'
import { useApi } from '../lib/useApi'

function StatusPill({ icon: Icon, label, value, ok }) {
  return (
    <div className="card tight row" style={{ gap: 12 }}>
      <span className="list-icon" style={{ color: ok ? 'var(--good)' : 'var(--warn)' }}><Icon size={17} /></span>
      <div className="grow">
        <div className="xsmall muted">{label}</div>
        <div className="small truncate" style={{ fontWeight: 650 }}>{value}</div>
      </div>
      <span className="dot" style={{ background: ok ? 'var(--good)' : 'var(--warn)' }} aria-hidden="true" />
    </div>
  )
}

function NewsletterModal({ onClose, onDone }) {
  const { t } = useLanguage()
  const toast = useToast()
  const [text, setText] = useState(t('auto.newsletter_example'))
  const [busy, setBusy] = useState(false)
  async function submit() {
    setBusy(true)
    try {
      const { run } = await api.post('/api/notifications/ingest', { text })
      toast(run.summary, run.status === 'error' ? 'error' : 'success')
      onDone()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title={t('auto.newsletter_title')} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>{t('common.cancel')}</button><button className="btn primary" onClick={submit} disabled={busy || text.trim().length < 10}>{busy ? <Spinner /> : <Sparkles size={16} />} {t('auto.publish')}</button></>}>
      <p className="small muted" style={{ marginBottom: 12 }}>{t('auto.newsletter_hint')}</p>
      <textarea className="textarea" rows={9} value={text} onChange={(e) => setText(e.target.value)} aria-label={t('auto.newsletter_title')} />
    </Modal>
  )
}

function JobCard({ job, onRun, running }) {
  const { t, language } = useLanguage()
  const toast = useToast()
  const Icon = JOB_ICONS[job.name] || Workflow
  const last = job.last_run
  const command = `python -m caffein run ${job.name}`
  return (
    <article className="card stack" style={{ gap: 14 }}>
      <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
        <span className="stat-icon" style={{ width: 38, height: 38, borderRadius: 11, background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Icon size={18} /></span>
        <div className="grow">
          <h3 style={{ fontSize: 16 }}>{t(`jobs.${job.name}.title`)}</h3>
          <div className="xsmall muted" style={{ marginTop: 3 }}>{t('auto.replaces')} <span style={{ color: 'var(--fg)' }}>{job.replaces}</span></div>
        </div>
      </div>
      <p className="small muted">{t(`jobs.${job.name}.desc`)}</p>
      <div className="stack sm small">
        <div className="row" style={{ gap: 8 }}><Clock size={14} className="muted" /> {job.schedule.type === 'event' ? t(`jobs.${job.name}.trigger`) : t(`auto.schedule_${job.schedule.type}`, { n: job.schedule.minutes, time: job.schedule.time })}</div>
        {job.next_run && <div className="row" style={{ gap: 8 }}><CalendarClock size={14} className="muted" /> {t('auto.next_run')} {relative(job.next_run, language)}</div>}
      </div>
      <div className="card tight" style={{ boxShadow: 'none', background: 'var(--surface-2)', padding: 12 }}>
        {last ? (
          <div className="stack sm">
            <div className="row between"><RunStatus status={last.status} /><span className="xsmall muted">{relative(last.started_at, language)}</span></div>
            <div className="small" style={{ lineHeight: 1.45 }}>{last.summary || '—'}</div>
          </div>
        ) : <div className="small muted">{job.last_check ? t('auto.checked', { when: relative(job.last_check, language) }) : t('auto.never')}</div>}
        {last && job.last_check && job.last_check > last.started_at && <div className="xsmall subtle" style={{ marginTop: 6 }}>{t('auto.checked', { when: relative(job.last_check, language) })}</div>}
      </div>
      <div className="row" style={{ marginTop: 'auto' }}>
        <button className="code grow row" style={{ cursor: 'copy', gap: 8, textAlign: 'left' }} title={t('auto.copy')}
          onClick={() => navigator.clipboard?.writeText(command).then(() => toast(t('auto.copied')))}>
          <Terminal size={13} /><span className="truncate">{command}</span><Copy size={13} style={{ marginLeft: 'auto' }} />
        </button>
        {job.manual ? (
          <button className="btn sm primary" onClick={() => onRun(job)} disabled={running}>{running ? <Spinner /> : <Play size={14} />} {t('auto.run')}</button>
        ) : <span className="badge outline" title={t('auto.event_hint')}>{t('auto.event')}</span>}
      </div>
    </article>
  )
}

function Outbox() {
  const { t, language } = useLanguage()
  const { data, loading } = useApi('/api/emails')
  const [kind, setKind] = useState('all')
  const [picked, setSelected] = useState(null)
  const list = useMemo(() => (data || []).filter((e) => kind === 'all' || e.kind === kind), [data, kind])
  const selected = (picked && list.find((e) => e.id === picked.id)) || list[0] || null

  if (loading) return <div className="skeleton" style={{ height: 300 }} />
  if (!data?.length) return <EmptyState icon={Inbox} title={t('auto.outbox_empty')} />
  return (
    <div className="grid outbox-grid">
      <div className="card flush">
        <div className="chips" style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
          {['all', 'invoice', 'quote', 'reminder', 'notification', 'onboarding', 'alert'].map((k) => (
            <button key={k} className={`chip ${kind === k ? 'active' : ''}`} onClick={() => setKind(k)}>{t(`mailkind.${k}`)}</button>
          ))}
        </div>
        <div style={{ maxHeight: 620, overflowY: 'auto' }}>
          {list.map((e) => (
            <button key={e.id} onClick={() => setSelected(e)} className="list-item"
              style={{ width: '100%', border: 0, borderBottom: '1px solid var(--border)', padding: '12px 14px', cursor: 'pointer', textAlign: 'left',
                background: selected?.id === e.id ? 'var(--surface-2)' : 'transparent' }}>
              <span className="list-icon">{selected?.id === e.id ? <MailOpen size={16} /> : <Mail size={16} />}</span>
              <div className="grow">
                <div className="small truncate" style={{ fontWeight: 600 }}>{e.subject}</div>
                <div className="xsmall muted truncate">{t('auto.to')} {e.to_email} · {relative(e.created_at, language)}</div>
              </div>
              <EmailStatus status={e.status} />
            </button>
          ))}
        </div>
      </div>
      {selected && (
        <div className="card flush outbox-preview">
          <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontWeight: 650 }}>{selected.subject}</div>
            <div className="xsmall muted" style={{ marginTop: 4 }}>
              {selected.from_email} → {selected.to_email} · {date(selected.created_at, language, 'time')}
              {selected.attachment_name && <> · <Paperclip size={12} style={{ display: 'inline', verticalAlign: '-2px' }} /> {selected.attachment_name}</>}
            </div>
            {selected.error && <div className="xsmall" style={{ color: 'var(--bad)', marginTop: 4 }}>{selected.error}</div>}
          </div>
          <iframe title={selected.subject} src={`/api/emails/${selected.id}/html`} sandbox=""
            style={{ width: '100%', height: 560, border: 0, background: '#f4f4f5' }} />
        </div>
      )}
    </div>
  )
}

export default function Automations() {
  const { t, language } = useLanguage()
  const toast = useToast()
  const [tab, setTab] = useState('scripts')
  const [running, setRunning] = useState('')
  const [newsletter, setNewsletter] = useState(false)
  const [detail, setDetail] = useState(null)
  const info = useApi('/api/automations')
  const runs = useApi(tab === 'history' ? '/api/automations/runs?limit=100' : null)

  useEffect(() => {
    const timer = setInterval(info.reload, 15000)
    return () => clearInterval(timer)
  }, [info.reload])

  async function runJob(job) {
    if (job.name === 'newsletter_notifications' && !info.data?.imap) return setNewsletter(true)
    setRunning(job.name)
    try {
      const result = await api.post(`/api/automations/${job.name}/run`)
      toast(result.summary || t('auto.done'), result.status === 'error' ? 'error' : 'success')
      info.reload()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setRunning('')
    }
  }

  const d = info.data
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('auto.title')}</h1>
          <p className="page-sub">{t('auto.subtitle')}</p>
        </div>
      </div>

      <div className="grid grid-3">
        <StatusPill icon={Bot} label={t('auto.ai')} ok={d?.ai?.mode === 'claude'}
          value={d ? (d.ai.mode === 'claude' ? `Claude · ${d.ai.model}` : t('auto.ai_offline')) : '…'} />
        <StatusPill icon={Mail} label={t('auto.email')} ok={d?.email?.mode === 'resend'}
          value={d ? (d.email.mode === 'resend' ? `Resend · ${d.email.from}` : t('auto.email_sim')) : '…'} />
        <StatusPill icon={Server} label={t('auto.scheduler')} ok={d?.scheduler}
          value={d ? (d.scheduler ? t('auto.scheduler_on') : t('auto.scheduler_off')) : '…'} />
      </div>
      {d && (d.ai.mode !== 'claude' || d.email.mode !== 'resend') && (
        <p className="xsmall muted" style={{ marginTop: 10 }}>{t('auto.env_hint')}</p>
      )}

      <div className="tabs section-gap" role="tablist">
        {[['scripts', Workflow], ['history', History], ['outbox', Inbox]].map(([key, Icon]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
            <Icon size={15} /> {t(`auto.tab_${key}`)}
          </button>
        ))}
      </div>

      {tab === 'scripts' && (
        d ? (
          <div className="grid grid-3">
            {d.jobs.map((job) => <JobCard key={job.name} job={job} onRun={runJob} running={running === job.name || job.running} />)}
          </div>
        ) : <div className="skeleton" style={{ height: 320 }} />
      )}

      {tab === 'history' && (
        <div className="card flush">
          {runs.data?.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>{t('auto.when')}</th><th>{t('auto.script')}</th><th className="hide-mobile">{t('auto.trigger')}</th><th>{t('invoices.status')}</th><th>{t('auto.summary')}</th></tr></thead>
                <tbody>
                  {runs.data.map((r) => (
                    <tr key={r.id} className="clickable" onClick={() => setDetail(r)}>
                      <td className="small nowrap">{date(r.started_at, language, 'time')}</td>
                      <td className="small nowrap" style={{ fontWeight: 600 }}>{t(`jobs.${r.job}.title`)}</td>
                      <td className="hide-mobile"><span className="badge outline">{t(`trigger.${r.trigger}`)}</span></td>
                      <td><RunStatus status={r.status} /></td>
                      <td className="small"><span className="truncate" style={{ display: 'block', maxWidth: 420 }}>{r.summary}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : runs.loading ? <div style={{ padding: 20 }}><Spinner /></div> : <EmptyState icon={History} title={t('auto.history_empty')} />}
        </div>
      )}

      {tab === 'outbox' && <Outbox />}

      {newsletter && <NewsletterModal onClose={() => setNewsletter(false)} onDone={() => { setNewsletter(false); info.reload() }} />}
      {detail && (
        <Modal title={`${t(`jobs.${detail.job}.title`)} — ${date(detail.started_at, language, 'time')}`} onClose={() => setDetail(null)} wide>
          <div className="row" style={{ gap: 8, marginBottom: 12 }}><RunStatus status={detail.status} /><span className="badge outline">{t(`trigger.${detail.trigger}`)}</span></div>
          <p style={{ marginBottom: 12 }}>{detail.summary}</p>
          <pre className="code" style={{ whiteSpace: 'pre-wrap', maxHeight: 420, overflow: 'auto' }}>{JSON.stringify(detail.details, null, 2)}</pre>
        </Modal>
      )}
    </div>
  )
}
