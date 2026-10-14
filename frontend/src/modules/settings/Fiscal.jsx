// SPDX-License-Identifier: AGPL-3.0-or-later
import { Segmented, Spinner, Toggle } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'
import SaveButton from './SaveButton'
import SettingsPage, { Field } from './SettingsPage'
import { useProfileForm } from './useProfileForm'

export default function Fiscal() {
  const { t, language } = useLanguage()
  const { profile, form, setForm, set, dirty, saving, save } = useProfileForm()
  return (
    <SettingsPage title={t('settings.tab_fiscal')} actions={<SaveButton onClick={save} disabled={!dirty} saving={saving} />}>
      {!profile ? <Spinner /> : (
        <div className="card" style={{ maxWidth: 820 }}>
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
        </div>
      )}
    </SettingsPage>
  )
}
