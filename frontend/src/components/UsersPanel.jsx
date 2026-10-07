// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { KeyRound, Trash2, UserPlus } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useLanguage } from '../context/LanguageContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'
import { relative } from '../lib/format'
import { useApi } from '../lib/useApi'
import { Modal, Spinner, Toggle } from './ui'

const blank = { full_name: '', email: '', role: 'member', password: '' }

// Gestion des comptes (administrateurs uniquement)
export default function UsersPanel() {
  const { t, language } = useLanguage()
  const { user: me } = useAuth()
  const toast = useToast()
  const { data: users, reload } = useApi('/api/users')
  const [form, setForm] = useState(blank)
  const [busy, setBusy] = useState(false)
  const [resetting, setResetting] = useState(null)
  const [newPassword, setNewPassword] = useState('')

  async function call(promise, message) {
    try {
      await promise
      if (message) toast(message)
      reload()
      return true
    } catch (err) {
      toast(err.message, 'error')
      return false
    }
  }

  async function create(e) {
    e.preventDefault()
    setBusy(true)
    if (await call(api.post('/api/users', form), t('users.created'))) setForm(blank)
    setBusy(false)
  }

  return (
    <div className="stack lg">
      <div className="list">
        {(users || []).map((u) => (
          <div className="list-item" key={u.id} style={{ alignItems: 'flex-start' }}>
            <span className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>{(u.full_name || u.email)[0].toUpperCase()}</span>
            <div className="grow">
              <div className="small" style={{ fontWeight: 650 }}>{u.full_name || '—'} {u.id === me?.id && <span className="subtle">({t('users.you')})</span>}</div>
              <div className="xsmall muted truncate">{u.email}</div>
              <div className="xsmall subtle">{u.last_login_at ? t('users.last_login', { when: relative(u.last_login_at, language) }) : t('users.never')}</div>
              {u.id !== me?.id && (
                <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
                  <select className="select sm" style={{ width: 150 }} value={u.role} aria-label={t('users.role')}
                    onChange={(e) => call(api.put(`/api/users/${u.id}`, { role: e.target.value }), t('settings.saved'))}>
                    <option value="admin">{t('role.admin')}</option>
                    <option value="member">{t('role.member')}</option>
                  </select>
                  <label className="row xsmall muted" style={{ gap: 6 }}>
                    <Toggle checked={u.active} label={t('users.active')}
                      onChange={(v) => call(api.put(`/api/users/${u.id}`, { active: v }), t('settings.saved'))} />
                    {t('users.active')}
                  </label>
                  <button className="icon-btn" title={t('users.reset_password')} aria-label={t('users.reset_password')}
                    onClick={() => { setResetting(u); setNewPassword('') }}><KeyRound size={15} /></button>
                  <button className="icon-btn" title={t('common.delete')} aria-label={t('common.delete')}
                    onClick={() => window.confirm(t('users.delete_confirm', { name: u.email })) && call(api.del(`/api/users/${u.id}`), t('users.deleted'))}>
                    <Trash2 size={15} />
                  </button>
                </div>
              )}
            </div>
            <span className={`badge ${u.role === 'admin' ? 'accent' : ''}`}>{t(`role.${u.role}`)}</span>
          </div>
        ))}
        {!users && <Spinner />}
      </div>

      <form className="card tight stack" style={{ boxShadow: 'none' }} onSubmit={create}>
        <div className="card-title"><UserPlus size={16} /> {t('users.add')}</div>
        <div className="form-grid">
          <div className="field"><label>{t('settings.full_name')}</label><input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
          <div className="field"><label>{t('login.email')}</label><input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div className="field">
            <label>{t('users.role')}</label>
            <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="member">{t('role.member')}</option>
              <option value="admin">{t('role.admin')}</option>
            </select>
          </div>
          <div className="field">
            <label>{t('users.temp_password')}</label>
            <input className="input" type="text" autoComplete="off" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
        </div>
        <p className="xsmall subtle">{t('users.roles_hint')}</p>
        <div className="row end"><button className="btn dark" disabled={busy}>{busy ? <Spinner /> : <UserPlus size={15} />} {t('users.create')}</button></div>
      </form>

      {resetting && (
        <Modal title={t('users.reset_title', { name: resetting.email })} onClose={() => setResetting(null)}
          footer={(
            <>
              <button className="btn" onClick={() => setResetting(null)}>{t('common.cancel')}</button>
              <button className="btn primary" disabled={newPassword.length < 8} onClick={async () => {
                if (await call(api.post(`/api/users/${resetting.id}/password`, { password: newPassword }), t('settings.password_changed'))) setResetting(null)
              }}>{t('users.reset_password')}</button>
            </>
          )}>
          <div className="field">
            <label>{t('settings.new_password')}</label>
            <input className="input" type="text" autoComplete="off" autoFocus value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            <span className="hint">{t('users.reset_hint')}</span>
          </div>
        </Modal>
      )}
    </div>
  )
}
