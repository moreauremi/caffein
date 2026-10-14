// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { KeyRound, ShieldCheck, Trash2, UserPlus } from 'lucide-react'
import NamedIcon from '../../components/NamedIcon'
import { Modal, Spinner, Toggle } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { relative } from '../../lib/format'
import { LEVEL_NAMES } from '../../lib/meta'
import { useApi } from '../../lib/useApi'
import SettingsPage, { Field } from './SettingsPage'

const blank = { full_name: '', email: '', role: 'member', role_id: '', password: '' }

// Dérogations par module pour un utilisateur : « selon le rôle » ou un niveau choisi
function AccessModal({ user, roles, modules, onClose, onSaved }) {
  const { t, pick } = useLanguage()
  const toast = useToast()
  const [overrides, setOverrides] = useState(() => ({ ...user.overrides }))
  const [busy, setBusy] = useState(false)
  const role = roles.find((r) => r.id === user.role_id)
  const roleLevel = (key) => (role ? (role.permissions[key] ?? role.default_level) : 0)

  async function save() {
    setBusy(true)
    try {
      const payload = Object.fromEntries(modules.map((m) => [m.key, overrides[m.key] ?? null]))
      await api.put(`/api/users/${user.id}/permissions`, { overrides: payload })
      toast(t('users.access_saved'))
      onSaved()
      onClose()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={t('users.access_title', { name: user.full_name || user.email })} onClose={onClose} wide
      footer={(
        <>
          <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button className="btn primary" disabled={busy} onClick={save}>{busy ? <Spinner /> : null} {t('common.save')}</button>
        </>
      )}>
      <p className="small muted" style={{ marginBottom: 14 }}>{t('users.access_hint')}</p>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>{t('roles.module')}</th><th>{t('users.edit_access')}</th></tr></thead>
          <tbody>
            {modules.map((m) => (
              <tr key={m.key}>
                <td>
                  <span className="row" style={{ gap: 8 }}>
                    <NamedIcon name={m.icon} /> {pick(m.label)}
                    {!m.enabled ? <span className="badge outline">{t('roles.inactive')}</span> : null}
                  </span>
                </td>
                <td style={{ width: 260 }}>
                  <select className="select sm" aria-label={pick(m.label)} value={overrides[m.key] ?? ''}
                    onChange={(e) => setOverrides((o) => ({ ...o, [m.key]: e.target.value === '' ? null : Number(e.target.value) }))}>
                    <option value="">{t('users.follow_role', { level: t(`level.${LEVEL_NAMES[roleLevel(m.key)]}`) })}</option>
                    {LEVEL_NAMES.map((name, level) => <option key={name} value={level}>{t(`level.${name}`)}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  )
}

// Comptes, type (administrateur ou membre), rôle métier et dérogations par module (administrateurs uniquement)
export default function Users() {
  const { t, language } = useLanguage()
  const { user: me } = useAuth()
  const { reload: reloadMeta } = useMeta()
  const toast = useToast()
  const { data: users, reload } = useApi('/api/users')
  const { data: roleData } = useApi('/api/settings/roles')
  const [form, setForm] = useState(blank)
  const [busy, setBusy] = useState(false)
  const [resetting, setResetting] = useState(null)
  const [newPassword, setNewPassword] = useState('')
  const [editing, setEditing] = useState(null)
  const roles = roleData?.roles || []
  const modules = roleData?.modules || []

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
    const payload = { ...form, role_id: form.role === 'member' && form.role_id ? Number(form.role_id) : null }
    if (await call(api.post('/api/users', payload), t('users.created'))) setForm(blank)
    setBusy(false)
  }

  return (
    <SettingsPage title={t('settings.tab_users')} wide>
      <div className="grid users-grid">
        <div className="card">
          <div className="list">
            {(users || []).map((u) => (
              <div className="list-item" key={u.id} style={{ alignItems: 'flex-start' }}>
                <span className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>{(u.full_name || u.email)[0].toUpperCase()}</span>
                <div className="grow">
                  <div className="row wrap" style={{ gap: 8 }}>
                    <span className="small" style={{ fontWeight: 650 }}>{u.full_name || '—'} {u.id === me?.id && <span className="subtle">({t('users.you')})</span>}</span>
                    <span className={`badge ${u.role === 'admin' ? 'accent' : ''}`}>{t(`role.${u.role}`)}</span>
                    {u.role !== 'admin' ? <span className="badge outline">{roles.find((r) => r.id === u.role_id)?.name || t('users.no_role')}</span> : null}
                    {!u.active ? <span className="badge bad">{t('users.inactive')}</span> : null}
                  </div>
                  <div className="xsmall muted truncate">{u.email}</div>
                  <div className="xsmall subtle">{u.last_login_at ? t('users.last_login', { when: relative(u.last_login_at, language) }) : t('users.never')}</div>
                  {u.id !== me?.id && (
                    <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
                      <select className="select sm" style={{ width: 150 }} value={u.role} aria-label={t('users.account_type')}
                        onChange={(e) => call(api.put(`/api/users/${u.id}`, { role: e.target.value }), t('settings.saved'))}>
                        <option value="admin">{t('role.admin')}</option>
                        <option value="member">{t('role.member')}</option>
                      </select>
                      {u.role !== 'admin' && (
                        <select className="select sm" style={{ width: 190 }} value={u.role_id ?? ''} aria-label={t('users.business_role')}
                          onChange={(e) => call(api.put(`/api/users/${u.id}`, { role_id: e.target.value ? Number(e.target.value) : null }), t('settings.saved'))}>
                          {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                        </select>
                      )}
                      {u.role !== 'admin' && (
                        <button className="btn sm" onClick={() => setEditing(u)}>
                          <ShieldCheck size={14} /> {t('users.edit_access')}
                          {Object.keys(u.overrides || {}).length ? <span className="badge accent">{Object.keys(u.overrides).length}</span> : null}
                        </button>
                      )}
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
                  {u.role === 'admin' && u.id !== me?.id ? <p className="xsmall subtle" style={{ marginTop: 6 }}>{t('users.admin_all')}</p> : null}
                </div>
              </div>
            ))}
            {!users && <Spinner />}
          </div>
        </div>

        <form className="card stack" onSubmit={create}>
          <div className="card-title"><UserPlus size={16} /> {t('users.add')}</div>
          <Field label={t('settings.full_name')}><input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label={t('login.email')}><input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label={t('users.account_type')}>
            <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="member">{t('role.member')}</option>
              <option value="admin">{t('role.admin')}</option>
            </select>
          </Field>
          {form.role === 'member' && (
            <Field label={t('users.business_role')}>
              <select className="select" value={form.role_id} onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
                <option value="">{roles.find((r) => r.key === 'team')?.name || '—'}</option>
                {roles.filter((r) => r.key !== 'team').map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </Field>
          )}
          <Field label={t('users.temp_password')}>
            <input className="input" type="text" autoComplete="off" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <p className="xsmall subtle">{t('users.roles_hint')}</p>
          <div className="row end"><button className="btn dark" disabled={busy}>{busy ? <Spinner /> : <UserPlus size={15} />} {t('users.create')}</button></div>
        </form>
      </div>

      {editing && (
        <AccessModal user={editing} roles={roles} modules={modules} onClose={() => setEditing(null)}
          onSaved={() => { reload(); if (editing.id === me?.id) reloadMeta() }} />
      )}

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
    </SettingsPage>
  )
}
