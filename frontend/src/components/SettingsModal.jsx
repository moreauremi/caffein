// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import {
  Bell, Building2, Database, ExternalLink, Info, KeyRound, Landmark, Palette, RotateCcw, Save, Scale, Trash2, UserRound, UsersRound,
} from 'lucide-react'
import { useApp } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import { useLanguage } from '../context/LanguageContext'
import { useTheme } from '../context/ThemeContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'
import UsersPanel from './UsersPanel'
import { ConfirmButton, Drawer, Segmented, Spinner, Toggle } from './ui'

const TABS = [
  { key: 'me', icon: UserRound },
  { key: 'appearance', icon: Palette },
  { key: 'company', icon: Building2, admin: true },
  { key: 'notifications', icon: Bell, admin: true },
  { key: 'fiscal', icon: Landmark, admin: true },
  { key: 'users', icon: UsersRound, admin: true },
  { key: 'about', icon: Info },
]
const PROFILE_TABS = new Set(['company', 'notifications', 'fiscal'])

function Field({ label, hint, children, full = false }) {
  return (
    <div className={`field ${full ? 'full' : ''}`}>
      <label>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}

function MyAccount() {
  const { t } = useLanguage()
  const { user, setUser } = useAuth()
  const toast = useToast()
  const [me, setMe] = useState({ full_name: user?.full_name || '', email: user?.email || '' })
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' })
  const [busy, setBusy] = useState('')

  async function saveMe(e) {
    e.preventDefault()
    setBusy('me')
    try {
      setUser(await api.put('/api/auth/me', me))
      toast(t('settings.saved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy('')
    }
  }

  async function savePassword(e) {
    e.preventDefault()
    if (pw.new_password !== pw.confirm) return toast(t('setup.err_confirm'), 'error')
    setBusy('pw')
    try {
      await api.post('/api/auth/password', { current_password: pw.current_password, new_password: pw.new_password })
      setPw({ current_password: '', new_password: '', confirm: '' })
      toast(t('settings.password_changed'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="stack lg">
      <form className="form-grid" onSubmit={saveMe}>
        <Field label={t('settings.full_name')}><input className="input" value={me.full_name} onChange={(e) => setMe({ ...me, full_name: e.target.value })} /></Field>
        <Field label={t('login.email')}><input className="input" type="email" value={me.email} onChange={(e) => setMe({ ...me, email: e.target.value })} /></Field>
        <div className="full row end">
          <button className="btn" disabled={busy === 'me'}>{busy === 'me' ? <Spinner /> : <Save size={15} />} {t('common.save')}</button>
        </div>
      </form>
      {user?.is_demo ? (
        <div className="alert info small"><Info size={16} /><span>{t('settings.demo_account')}</span></div>
      ) : (
        <form className="card tight stack" style={{ boxShadow: 'none' }} onSubmit={savePassword}>
          <div className="card-title"><KeyRound size={16} /> {t('settings.password_title')}</div>
          <div className="form-grid">
            <Field label={t('settings.current_password')} full>
              <input className="input" type="password" autoComplete="current-password" value={pw.current_password}
                onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
            </Field>
            <Field label={t('settings.new_password')} hint={t('setup.password_hint')}>
              <input className="input" type="password" autoComplete="new-password" value={pw.new_password}
                onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            </Field>
            <Field label={t('setup.confirm')}>
              <input className="input" type="password" autoComplete="new-password" value={pw.confirm}
                onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
            </Field>
          </div>
          <div className="row end">
            <button className="btn dark" disabled={busy === 'pw' || !pw.current_password || !pw.new_password}>
              {busy === 'pw' ? <Spinner /> : <KeyRound size={15} />} {t('settings.change_password')}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

function About() {
  const { t } = useLanguage()
  const { config } = useApp()
  if (!config) return <Spinner />
  return (
    <div className="stack lg">
      <div className="card tight" style={{ boxShadow: 'none' }}>
        <div className="row" style={{ gap: 12 }}>
          <span className="stat-icon"><Scale size={16} /></span>
          <div className="grow">
            <div style={{ fontWeight: 650 }}>Caffein {config.version}</div>
            <div className="small muted">{t('about.license', { license: config.license })}</div>
          </div>
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>{t('about.agpl')}</p>
        {config.source_url ? (
          <a className="btn sm" style={{ marginTop: 12 }} href={config.source_url} target="_blank" rel="noreferrer">
            <ExternalLink size={14} /> {t('about.source')}
          </a>
        ) : (
          <p className="xsmall subtle" style={{ marginTop: 10 }}>{t('about.source_missing')}</p>
        )}
      </div>
      <div className="stack sm small">
        {[
          [t('auto.ai'), config.ai.mode === 'claude' ? `Claude · ${config.ai.model}` : t('auto.ai_offline')],
          [t('auto.email'), config.email.provider || t('auto.email_sim')],
          [t('auto.scheduler'), config.scheduler ? t('auto.scheduler_on') : t('auto.scheduler_off')],
          [t('about.schema'), `v${config.schema}`],
          [t('about.url'), config.app_url],
        ].map(([label, value]) => (
          <div className="row between" key={label} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
            <span className="muted">{label}</span><span className="small" style={{ textAlign: 'right' }}>{value}</span>
          </div>
        ))}
      </div>
      <p className="xsmall subtle row" style={{ gap: 6 }}><Database size={13} /> {t('about.backup_hint')}</p>
    </div>
  )
}

export default function SettingsModal() {
  const { profile, setProfile, settingsTab, openSettings, closeSettings } = useApp()
  const { user } = useAuth()
  const { t, language, setLanguage } = useLanguage()
  const { theme, setTheme } = useTheme()
  const toast = useToast()
  const [form, setForm] = useState(profile || {})
  const [saving, setSaving] = useState(false)
  const [syncedProfile, setSyncedProfile] = useState(profile)
  if (profile !== syncedProfile) {
    // le profil a été rechargé (sauvegarde, réinitialisation) : on resynchronise le formulaire
    setSyncedProfile(profile)
    setForm(profile || {})
  }

  const isAdmin = user?.role === 'admin'
  const tabs = TABS.filter((tab) => !tab.admin || isAdmin)
  const current = tabs.some((tab) => tab.key === settingsTab) ? settingsTab : 'me'
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e?.target ? e.target.value : e }))
  const dirty = profile && JSON.stringify(form) !== JSON.stringify(profile)

  async function save() {
    setSaving(true)
    try {
      setProfile(await api.put('/api/profile', form))
      toast(t('settings.saved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function reset(mode) {
    await api.post('/api/admin/reset', { mode })
    toast(t('settings.reset_done'))
    setTimeout(() => window.location.reload(), 600)
  }

  return (
    <Drawer title={t('settings.title')} subtitle={t('settings.subtitle')} onClose={closeSettings} narrow
      footer={PROFILE_TABS.has(current) && (
        <>
          <button className="btn" onClick={closeSettings}>{t('common.close')}</button>
          <button className="btn primary" onClick={save} disabled={!dirty || saving}>
            {saving ? <Spinner /> : <Save size={16} />} {t('common.save')}
          </button>
        </>
      )}>
      <div className="tabs" role="tablist">
        {tabs.map(({ key, icon: Icon }) => (
          <button key={key} role="tab" aria-selected={current === key} className={current === key ? 'active' : ''}
            onClick={() => openSettings(key)}>
            <Icon size={15} /> {t(`settings.tab_${key}`)}
          </button>
        ))}
      </div>

      {current === 'me' && <MyAccount />}
      {current === 'about' && <About />}
      {current === 'users' && <UsersPanel />}

      {current === 'appearance' && (
        <div className="stack lg">
          <div className="toggle-row">
            <div>
              <div style={{ fontWeight: 600 }}>{t('settings.theme')}</div>
              <div className="small muted">{t('settings.theme_hint')}</div>
            </div>
            <Segmented value={theme} onChange={setTheme} label={t('settings.theme')}
              options={[{ value: 'clair', label: t('settings.light') }, { value: 'sombre', label: t('settings.dark') }]} />
          </div>
          <div className="toggle-row">
            <div>
              <div style={{ fontWeight: 600 }}>{t('settings.language')}</div>
              <div className="small muted">{t('settings.language_hint')}</div>
            </div>
            <Segmented value={language} onChange={setLanguage} label={t('settings.language')}
              options={[{ value: 'fr', label: 'Français' }, { value: 'en', label: 'English' }]} />
          </div>
        </div>
      )}

      {PROFILE_TABS.has(current) && !profile && <Spinner />}

      {profile && current === 'company' && (
        <div className="stack lg">
          <div className="form-grid">
            <Field label={t('settings.company')}><input className="input" value={form.company || ''} onChange={set('company')} /></Field>
            <Field label={t('settings.manager')}><input className="input" value={form.full_name || ''} onChange={set('full_name')} /></Field>
            <Field label={t('settings.email')} hint={t('settings.email_hint')}><input className="input" type="email" value={form.email || ''} onChange={set('email')} /></Field>
            <Field label={t('settings.phone')}><input className="input" value={form.phone || ''} onChange={set('phone')} /></Field>
            <Field label={t('settings.address')} full><input className="input" value={form.address || ''} onChange={set('address')} /></Field>
            <Field label={t('settings.zip')}><input className="input" value={form.zip_code || ''} onChange={set('zip_code')} /></Field>
            <Field label={t('settings.city')}><input className="input" value={form.city || ''} onChange={set('city')} /></Field>
            <Field label="SIRET"><input className="input mono" value={form.siret || ''} onChange={set('siret')} /></Field>
            <Field label={t('settings.naf')}><input className="input mono" value={form.naf_code || ''} onChange={set('naf_code')} /></Field>
            <Field label="IBAN" full hint={t('settings.iban_hint')}><input className="input mono" value={form.iban || ''} onChange={set('iban')} /></Field>
            <Field label="BIC"><input className="input mono" value={form.bic || ''} onChange={set('bic')} /></Field>
          </div>
          <div className="card tight stack" style={{ borderColor: 'color-mix(in srgb, var(--bad) 30%, transparent)', boxShadow: 'none' }}>
            <div style={{ fontWeight: 650 }}>{t('settings.danger')}</div>
            <div className="row between wrap">
              <div className="grow small muted" style={{ minWidth: 200 }}>{t('settings.erase_text')}</div>
              <ConfirmButton confirmLabel={t('settings.reset_confirm')} onConfirm={() => reset('empty')}>
                <Trash2 size={15} /> {t('settings.erase_button')}
              </ConfirmButton>
            </div>
            <div className="row between wrap">
              <div className="grow small muted" style={{ minWidth: 200 }}>{t('settings.demo_text')}</div>
              <ConfirmButton confirmLabel={t('settings.reset_confirm')} onConfirm={() => reset('demo')}>
                <RotateCcw size={15} /> {t('settings.demo_button')}
              </ConfirmButton>
            </div>
          </div>
        </div>
      )}

      {profile && current === 'notifications' && (
        <div>
          <div className="toggle-row">
            <div className="grow">
              <div style={{ fontWeight: 600 }}>{t('settings.notif_tva')}</div>
              <div className="small muted">{t('settings.notif_tva_hint')}</div>
              {form.notif_tva && (
                <div className="row" style={{ marginTop: 10, maxWidth: 260 }}>
                  <span className="small muted nowrap">{t('settings.threshold')}</span>
                  <input className="input sm num mono" type="number" min="0" step="50" value={form.tva_alert_threshold}
                    onChange={(e) => setForm((f) => ({ ...f, tva_alert_threshold: Number(e.target.value) }))} />
                  <span className="small muted">€</span>
                </div>
              )}
            </div>
            <Toggle checked={form.notif_tva} onChange={set('notif_tva')} label={t('settings.notif_tva')} />
          </div>
          {[
            ['notif_echeance', 'settings.notif_echeance', 'settings.notif_echeance_hint'],
            ['notif_hebdo', 'settings.notif_hebdo', 'settings.notif_hebdo_hint'],
            ['notif_onboarding', 'settings.notif_onboarding', 'settings.notif_onboarding_hint'],
          ].map(([key, label, hint]) => (
            <div className="toggle-row" key={key}>
              <div>
                <div style={{ fontWeight: 600 }}>{t(label)}</div>
                <div className="small muted">{t(hint)}</div>
              </div>
              <Toggle checked={form[key]} onChange={set(key)} label={t(label)} />
            </div>
          ))}
          <p className="xsmall subtle" style={{ marginTop: 12 }}>{t('settings.notif_footer', { email: form.email || '—' })}</p>
        </div>
      )}

      {profile && current === 'fiscal' && (
        <div className="stack lg">
          <div className="form-grid">
            <Field label={t('settings.activity')} full hint={t('settings.activity_hint')}>
              <select className="select" value={form.activity} onChange={set('activity')}>
                {['bnc', 'bnc_cipav', 'bic_services', 'bic_vente'].map((a) => <option key={a} value={a}>{t(`activity.${a}`)}</option>)}
              </select>
            </Field>
            <Field label={t('settings.frequency')} full>
              <Segmented value={form.declaration_frequency} onChange={set('declaration_frequency')} label={t('settings.frequency')}
                options={[{ value: 'monthly', label: t('settings.monthly') }, { value: 'quarterly', label: t('settings.quarterly') }]} />
            </Field>
          </div>
          <div>
            <div className="toggle-row">
              <div>
                <div style={{ fontWeight: 600 }}>{t('settings.vl')}</div>
                <div className="small muted">{t('settings.vl_hint')}</div>
              </div>
              <Toggle checked={form.versement_liberatoire} onChange={set('versement_liberatoire')} label={t('settings.vl')} />
            </div>
            <div className="toggle-row">
              <div>
                <div style={{ fontWeight: 600 }}>{t('settings.vat_exempt')}</div>
                <div className="small muted">{t('settings.vat_exempt_hint')}</div>
              </div>
              <Toggle checked={form.vat_exempt} onChange={set('vat_exempt')} label={t('settings.vat_exempt')} />
            </div>
          </div>
          <div className="form-grid">
            {!form.vat_exempt && (
              <>
                <Field label={t('settings.vat_rate')}>
                  <select className="select" value={form.default_vat_rate} onChange={(e) => setForm((f) => ({ ...f, default_vat_rate: Number(e.target.value) }))}>
                    {[0.2, 0.1, 0.055, 0.021].map((r) => <option key={r} value={r}>{(r * 100).toLocaleString(language)} %</option>)}
                  </select>
                </Field>
                <Field label={t('settings.vat_number')}><input className="input mono" value={form.vat_number || ''} onChange={set('vat_number')} /></Field>
              </>
            )}
            <Field label={t('settings.terms')} hint={t('settings.terms_hint')}>
              <input className="input num mono" type="number" min="0" max="60" value={form.payment_terms_days}
                onChange={(e) => setForm((f) => ({ ...f, payment_terms_days: Number(e.target.value) }))} />
            </Field>
            <Field label={t('settings.prefix')} hint={t('settings.prefix_hint', { prefix: form.invoice_prefix || 'CAFFEIN' })}>
              <input className="input mono" value={form.invoice_prefix || ''} onChange={set('invoice_prefix')} />
            </Field>
            <Field label={t('settings.legal')} full><input className="input" value={form.legal_mention || ''} onChange={set('legal_mention')} /></Field>
          </div>
        </div>
      )}
    </Drawer>
  )
}
