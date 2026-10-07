// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Save } from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'
import { Modal, Spinner } from './ui'

const FIELDS = [
  ['name', 'full'], ['contact_name'], ['email'], ['phone'], ['address', 'full'], ['zip_code'], ['city'], ['siren'], ['vat_number'],
]

export default function ClientModal({ client, onClose, onSaved }) {
  const { t } = useLanguage()
  const toast = useToast()
  const [form, setForm] = useState(client || {})
  const [saving, setSaving] = useState(false)

  async function save(e) {
    e?.preventDefault()
    setSaving(true)
    try {
      const saved = client?.id ? await api.put(`/api/clients/${client.id}`, form) : await api.post('/api/clients', form)
      toast(t('clients.saved'))
      onSaved(saved)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={client?.id ? t('clients.edit') : t('clients.new')} onClose={onClose}
      footer={(
        <>
          <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button className="btn primary" onClick={save} disabled={saving || !form.name}>{saving ? <Spinner /> : <Save size={16} />} {t('common.save')}</button>
        </>
      )}>
      <form className="form-grid" onSubmit={save}>
        {FIELDS.map(([key, full]) => (
          <div className={`field ${full ? 'full' : ''}`} key={key}>
            <label htmlFor={`client-${key}`}>{t(`clients.f_${key}`)}{key === 'name' ? ' *' : ''}</label>
            <input id={`client-${key}`} className={`input ${['siren', 'vat_number'].includes(key) ? 'mono' : ''}`}
              type={key === 'email' ? 'email' : 'text'} value={form[key] || ''} autoFocus={key === 'name'}
              onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))} />
          </div>
        ))}
        <button type="submit" hidden />
      </form>
    </Modal>
  )
}
