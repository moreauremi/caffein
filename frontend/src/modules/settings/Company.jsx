// SPDX-License-Identifier: AGPL-3.0-or-later
import { RotateCcw, Trash2 } from 'lucide-react'
import { ConfirmButton, Spinner } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import SaveButton from './SaveButton'
import SettingsPage, { Field } from './SettingsPage'
import { useProfileForm } from './useProfileForm'

export default function Company() {
  const { t } = useLanguage()
  const toast = useToast()
  const { profile, form, set, dirty, saving, save } = useProfileForm()

  async function reset(mode) {
    await api.post('/api/admin/reset', { mode })
    toast(t('settings.reset_done'))
    setTimeout(() => window.location.reload(), 600)
  }

  return (
    <SettingsPage title={t('settings.tab_company')} actions={<SaveButton onClick={save} disabled={!dirty} saving={saving} />}>
      {!profile ? <Spinner /> : (
        <div className="card" style={{ maxWidth: 820 }}>
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
        </div>
      )}
    </SettingsPage>
  )
}
