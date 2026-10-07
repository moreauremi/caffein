// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AlertCircle, LogIn, PlayCircle } from 'lucide-react'
import AuthAside from '../components/AuthAside'
import LanguageSwitch from '../components/LanguageSwitch'
import Logo from '../components/Logo'
import { Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useLanguage } from '../context/LanguageContext'
import './auth.css'

export default function Login() {
  const { t } = useLanguage()
  const { loading, user, needsSetup, demo, signIn, signInDemo } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const target = location.state?.from || '/'

  if (loading) return null
  if (needsSetup) return <Navigate to="/setup" replace />
  if (user) return <Navigate to={target} replace />

  async function submit(e) {
    e.preventDefault()
    setBusy('login')
    setError('')
    try {
      await signIn(email, password)
      navigate(target, { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function demoLogin() {
    setBusy('demo')
    try {
      await signInDemo()
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="auth">
      <AuthAside />
      <main className="auth-main">
        <div className="auth-top"><LanguageSwitch /></div>
        <div className="auth-card">
          <div className="only-mobile" style={{ marginBottom: 24 }}><Logo size={30} /></div>
          <h2 style={{ fontSize: 28, letterSpacing: '-0.03em' }}>{t('login.title')}</h2>
          <p className="muted" style={{ marginTop: 8 }}>{t('login.subtitle')}</p>

          {demo && (
            <div className="card tight" style={{ marginTop: 24, background: 'var(--accent-soft)', borderColor: 'transparent', boxShadow: 'none' }}>
              <div style={{ fontWeight: 650 }}>{t('login.demo_title')}</div>
              <p className="small muted" style={{ margin: '4px 0 12px' }}>{t('login.demo_text')}</p>
              <button className="btn primary block demo-btn" onClick={demoLogin} disabled={Boolean(busy)}>
                {busy === 'demo' ? <Spinner /> : <PlayCircle size={17} />} {t('login.demo_button')}
              </button>
            </div>
          )}

          <form className="stack" style={{ marginTop: 24, gap: 14 }} onSubmit={submit}>
            <div className="field">
              <label htmlFor="login-email">{t('login.email')}</label>
              <input id="login-email" className="input" type="email" autoComplete="username" required autoFocus={!demo}
                value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="login-password">{t('login.password')}</label>
              <input id="login-password" className="input" type="password" autoComplete="current-password" required
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            {error && <div className="alert bad small" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
            <button className={`btn lg block ${demo ? '' : 'primary'}`} disabled={Boolean(busy)}>
              {busy === 'login' ? <Spinner size={18} /> : <LogIn size={18} />}
              {busy === 'login' ? t('login.loading') : t('login.button')}
            </button>
          </form>
          <p className="xsmall subtle" style={{ marginTop: 18 }}>{t('login.forgot')}</p>
        </div>
      </main>
    </div>
  )
}
