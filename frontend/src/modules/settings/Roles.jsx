// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Plus, Save, ShieldCheck, Trash2 } from 'lucide-react'
import NamedIcon from '../../components/NamedIcon'
import { ConfirmButton, Drawer, EmptyState, Spinner } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { LEVEL_NAMES } from '../../lib/meta'
import { useApi } from '../../lib/useApi'
import LevelBadge from './LevelBadge'
import SettingsPage, { Field } from './SettingsPage'

const levelOf = (role, key) => role.permissions[key] ?? role.default_level

// Édition d'un rôle : nom, description, niveau par défaut et niveau par module
function RoleDrawer({ role, modules, onClose, onSaved }) {
  const { t, pick } = useLanguage()
  const toast = useToast()
  const isNew = !role.id
  const [form, setForm] = useState({
    name: role.name || '', description: role.description || '', default_level: role.default_level ?? 0,
    permissions: { ...(role.permissions || {}) },
  })
  const [busy, setBusy] = useState(false)

  async function save(e) {
    e?.preventDefault()
    setBusy(true)
    try {
      const saved = isNew ? await api.post('/api/settings/roles', form) : await api.put(`/api/settings/roles/${role.id}`, form)
      toast(t(isNew ? 'roles.created' : 'roles.saved'))
      onSaved(saved)
      onClose()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    try {
      await api.del(`/api/settings/roles/${role.id}`)
      toast(t('roles.deleted'))
      onSaved(null)
      onClose()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const setLevel = (key, value) => setForm((f) => {
    const permissions = { ...f.permissions }
    if (value === '') delete permissions[key]
    else permissions[key] = Number(value)
    return { ...f, permissions }
  })

  return (
    <Drawer title={isNew ? t('roles.new') : role.name} subtitle={role.is_system ? t('roles.system') : null} onClose={onClose} narrow
      footer={(
        <>
          {!isNew && !role.is_system && (
            <ConfirmButton className="btn danger" confirmLabel={t('entity.delete_confirm')} onConfirm={remove}>
              <Trash2 size={15} /> {t('common.delete')}
            </ConfirmButton>
          )}
          <span className="grow" />
          <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button className="btn primary" type="submit" form="role-form" disabled={busy || !form.name.trim()}>
            {busy ? <Spinner /> : <Save size={15} />} {t('common.save')}
          </button>
        </>
      )}>
      <form id="role-form" className="stack lg" onSubmit={save}>
        <Field label={t('roles.name')} htmlFor="role-name">
          <input id="role-name" className="input" required maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label={t('roles.description')} htmlFor="role-description">
          <input id="role-description" className="input" maxLength={240} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label={t('roles.default_level')} hint={t('roles.default_hint')} htmlFor="role-default">
          <select id="role-default" className="select" value={form.default_level} onChange={(e) => setForm({ ...form, default_level: Number(e.target.value) })}>
            {LEVEL_NAMES.map((name, level) => <option key={name} value={level}>{t(`level.${name}`)}</option>)}
          </select>
        </Field>
        <div>
          <div className="label" style={{ marginBottom: 8 }}>{t('users.access')}</div>
          <div className="list">
            {modules.map((m) => (
              <div className="list-item" key={m.key}>
                <span className="list-icon"><NamedIcon name={m.icon} /></span>
                <div className="grow">
                  <div className="small" style={{ fontWeight: 600 }}>{pick(m.label)}</div>
                  {!m.enabled ? <div className="xsmall subtle">{t('roles.inactive')}</div> : null}
                </div>
                <select className="select sm" style={{ width: 180 }} aria-label={pick(m.label)} value={form.permissions[m.key] ?? ''}
                  onChange={(e) => setLevel(m.key, e.target.value)}>
                  <option value="">{t('roles.default_option', { level: t(`level.${LEVEL_NAMES[form.default_level]}`) })}</option>
                  {LEVEL_NAMES.map((name, level) => <option key={name} value={level}>{t(`level.${name}`)}</option>)}
                </select>
              </div>
            ))}
          </div>
        </div>
        <div className="card tight small muted" style={{ boxShadow: 'none' }}>
          {LEVEL_NAMES.map((name) => <div key={name}><b>{t(`level.${name}`)}</b> · {t(`level.${name}_hint`)}</div>)}
        </div>
      </form>
    </Drawer>
  )
}

// Rôles et droits : la grille modules × rôles, et l'édition de chaque rôle
export default function Roles() {
  const { t, pick } = useLanguage()
  const { reload: reloadMeta } = useMeta()
  const { data, reload } = useApi('/api/settings/roles')
  const [editing, setEditing] = useState(null)
  const roles = data?.roles || []
  const modules = data?.modules || []

  return (
    <SettingsPage title={t('roles.title')} lead={t('roles.lead')} wide
      actions={<button className="btn primary" onClick={() => setEditing({})}><Plus size={16} /> {t('roles.new')}</button>}>
      {!data ? <Spinner /> : roles.length === 0 ? <EmptyState icon={ShieldCheck} title={t('roles.new')} /> : (
        <div className="card flush">
          <div className="table-wrap">
            <table className="table roles-matrix">
              <thead>
                <tr>
                  <th>{t('roles.module')}</th>
                  {roles.map((role) => (
                    <th key={role.id}>
                      <button type="button" className="th-sort" onClick={() => setEditing(role)}>{role.name}</button>
                      <div className="xsmall subtle" style={{ fontWeight: 500 }}>
                        {t('roles.users', { n: role.users })}{role.is_system ? ` · ${t('roles.system')}` : ''}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {modules.map((m) => (
                  <tr key={m.key} className={m.enabled ? undefined : 'muted-row'}>
                    <td>
                      <span className="row nowrap" style={{ gap: 8 }}>
                        <NamedIcon name={m.icon} /> {pick(m.label)}
                        {!m.enabled ? <span className="badge outline">{t('roles.inactive')}</span> : null}
                      </span>
                    </td>
                    {roles.map((role) => (
                      <td key={role.id}><LevelBadge level={levelOf(role, m.key)} inherited={!(m.key in role.permissions)} /></td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {editing && (
        <RoleDrawer role={editing} modules={modules} onClose={() => setEditing(null)}
          onSaved={() => { reload(); reloadMeta() }} />
      )}
    </SettingsPage>
  )
}
