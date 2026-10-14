// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Info, KeyRound, Save } from 'lucide-react'
import { Spinner } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import SettingsPage, { Field } from './SettingsPage'

export default function Account() {
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
    <SettingsPage title={t('settings.tab_me')}>
    <div className="stack lg" style={{ maxWidth: 720 }}>
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
    </SettingsPage>
  )
}
