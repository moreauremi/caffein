// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowLeft, ArrowRight, Check, Rocket } from 'lucide-react'
import AuthAside from '../components/AuthAside'
import LanguageSwitch from '../components/LanguageSwitch'
import Logo from '../components/Logo'
import { Segmented, Spinner, Toggle } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useLanguage } from '../context/LanguageContext'
import './auth.css'

const ACTIVITIES = ['bnc', 'bnc_cipav', 'bic_services', 'bic_vente']

function Field({ id, label, children, full, hint }) {
  return (
    <div className={`field ${full ? 'full' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}

// Assistant d'installation (premier lancement, comme l'installeur de GLPI)
export default function Setup() {
  const { t, language } = useLanguage()
  const { loading, needsSetup, completeSetup } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [org, setOrg] = useState({
    company: '', legal_mention: 'Entrepreneur individuel (EI)', siret: '', address: '', zip_code: '', city: '', email: '', phone: '',
    activity: 'bnc', declaration_frequency: 'monthly', vat_exempt: true, default_vat_rate: 0.2,
  })
  const [admin, setAdmin] = useState({ full_name: '', email: '', password: '', confirm: '' })
  const [demoData, setDemoData] = useState(false)

  if (loading) return null
  if (!needsSetup) return <Navigate to="/" replace />

  const setO = (k) => (e) => setOrg((o) => ({ ...o, [k]: e?.target ? e.target.value : e }))
  const setA = (k) => (e) => setAdmin((a) => ({ ...a, [k]: e.target.value }))

  function validate() {
    if (step === 0 && !org.company.trim()) return t('setup.err_company')
    if (step === 2) {
      if (!admin.full_name.trim() || !admin.email.includes('@')) return t('setup.err_admin')
      if (admin.password.length < 8) return t('setup.err_password')
      if (admin.password !== admin.confirm) return t('setup.err_confirm')
    }
    return ''
  }

  async function next(e) {
    e.preventDefault()
    const problem = validate()
    setError(problem)
    if (problem) return
    if (step < 2) return setStep(step + 1)
    setBusy(true)
    try {
      await completeSetup({
        organization: { ...org, full_name: admin.full_name, email: org.email || admin.email },
        admin: { full_name: admin.full_name, email: admin.email, password: admin.password },
        demo_data: demoData,
      })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <AuthAside />
      <main className="auth-main">
        <div className="auth-top"><LanguageSwitch /></div>
        <form className="auth-card wide" onSubmit={next} noValidate>
          <div className="only-mobile" style={{ marginBottom: 20 }}><Logo size={30} /></div>
          <div className="small muted">{t('setup.step', { n: step + 1 })}</div>
          <h2 style={{ fontSize: 28, letterSpacing: '-0.03em', marginTop: 4 }}>{t(`setup.title_${step}`)}</h2>
          <p className="muted" style={{ marginTop: 8 }}>{t(`setup.lead_${step}`)}</p>
          <div className="auth-steps" aria-hidden="true">{[0, 1, 2].map((i) => <span key={i} className={i <= step ? 'done' : ''} />)}</div>

          {step === 0 && (
            <div className="form-grid">
              <Field id="s-company" label={`${t('settings.company')} *`} full>
                <input id="s-company" className="input" value={org.company} onChange={setO('company')} autoFocus />
              </Field>
              <Field id="s-legal" label={t('settings.legal')} full hint={t('setup.legal_hint')}>
                <input id="s-legal" className="input" value={org.legal_mention} onChange={setO('legal_mention')} />
              </Field>
              <Field id="s-siret" label="SIRET"><input id="s-siret" className="input mono" value={org.siret} onChange={setO('siret')} /></Field>
              <Field id="s-phone" label={t('settings.phone')}><input id="s-phone" className="input" value={org.phone} onChange={setO('phone')} /></Field>
              <Field id="s-address" label={t('settings.address')} full><input id="s-address" className="input" value={org.address} onChange={setO('address')} /></Field>
              <Field id="s-zip" label={t('settings.zip')}><input id="s-zip" className="input" value={org.zip_code} onChange={setO('zip_code')} /></Field>
              <Field id="s-city" label={t('settings.city')}><input id="s-city" className="input" value={org.city} onChange={setO('city')} /></Field>
              <Field id="s-email" label={t('setup.company_email')} full hint={t('setup.company_email_hint')}>
                <input id="s-email" className="input" type="email" value={org.email} onChange={setO('email')} />
              </Field>
            </div>
          )}

          {step === 1 && (
            <div className="stack lg">
              <Field id="s-activity" label={t('settings.activity')} hint={t('settings.activity_hint')}>
                <select id="s-activity" className="select" value={org.activity} onChange={setO('activity')}>
                  {ACTIVITIES.map((a) => <option key={a} value={a}>{t(`activity.${a}`)}</option>)}
                </select>
              </Field>
              <Field id="s-freq" label={t('settings.frequency')}>
                <Segmented value={org.declaration_frequency} onChange={setO('declaration_frequency')} label={t('settings.frequency')}
                  options={[{ value: 'monthly', label: t('settings.monthly') }, { value: 'quarterly', label: t('settings.quarterly') }]} />
              </Field>
              <div className="toggle-row" style={{ borderTop: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{t('settings.vat_exempt')}</div>
                  <div className="small muted">{t('settings.vat_exempt_hint')}</div>
                </div>
                <Toggle checked={org.vat_exempt} onChange={setO('vat_exempt')} label={t('settings.vat_exempt')} />
              </div>
              {!org.vat_exempt && (
                <Field id="s-rate" label={t('settings.vat_rate')}>
                  <select id="s-rate" className="select" value={org.default_vat_rate} onChange={(e) => setOrg((o) => ({ ...o, default_vat_rate: Number(e.target.value) }))}>
                    {[0.2, 0.1, 0.055, 0.021].map((r) => <option key={r} value={r}>{(r * 100).toLocaleString(language)} %</option>)}
                  </select>
                </Field>
              )}
              <p className="xsmall subtle">{t('setup.fiscal_hint')}</p>
            </div>
          )}

          {step === 2 && (
            <div className="stack lg">
              <div className="form-grid">
                <Field id="s-name" label={`${t('settings.full_name')} *`} full>
                  <input id="s-name" className="input" value={admin.full_name} onChange={setA('full_name')} autoFocus autoComplete="name" />
                </Field>
                <Field id="s-admin-email" label={`${t('login.email')} *`} full hint={t('setup.admin_email_hint')}>
                  <input id="s-admin-email" className="input" type="email" value={admin.email} onChange={setA('email')} autoComplete="username" />
                </Field>
                <Field id="s-pw" label={`${t('login.password')} *`} hint={t('setup.password_hint')}>
                  <input id="s-pw" className="input" type="password" value={admin.password} onChange={setA('password')} autoComplete="new-password" />
                </Field>
                <Field id="s-pw2" label={`${t('setup.confirm')} *`}>
                  <input id="s-pw2" className="input" type="password" value={admin.confirm} onChange={setA('confirm')} autoComplete="new-password" />
                </Field>
              </div>
              <div className="toggle-row" style={{ borderTop: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{t('setup.demo')}</div>
                  <div className="small muted">{t('setup.demo_hint')}</div>
                </div>
                <Toggle checked={demoData} onChange={setDemoData} label={t('setup.demo')} />
              </div>
            </div>
          )}

          {error && <div className="alert bad small" role="alert" style={{ marginTop: 18 }}><AlertCircle size={16} /><span>{error}</span></div>}

          <div className="row between" style={{ marginTop: 26 }}>
            {step > 0 ? (
              <button type="button" className="btn" onClick={() => { setError(''); setStep(step - 1) }} disabled={busy}>
                <ArrowLeft size={16} /> {t('setup.back')}
              </button>
            ) : <span />}
            <button className="btn primary lg" disabled={busy}>
              {busy ? <Spinner /> : step < 2 ? <ArrowRight size={17} /> : <Rocket size={17} />}
              {step < 2 ? t('setup.next') : t('setup.install')}
            </button>
          </div>
          <p className="xsmall subtle row" style={{ marginTop: 22, gap: 6 }}><Check size={13} /> {t('setup.privacy')}</p>
        </form>
      </main>
    </div>
  )
}
