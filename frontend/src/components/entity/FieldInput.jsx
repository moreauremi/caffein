// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLanguage } from '../../context/LanguageContext'
import { Toggle } from '../ui'
import RefSelect from './RefSelect'

// Saisie d'un champ selon son type. Les valeurs sont envoyées telles quelles au serveur, qui les valide
// et les convertit (« 1 250,50 » → 1250.5) : un seul endroit décide de ce qui est correct.
export default function FieldInput({ field, value, label, onChange, entityKey, disabled = false, id, compact = false }) {
  const { t, pick } = useLanguage()
  const name = pick(field.label)
  const cls = compact ? 'sm' : ''
  const common = { id, disabled, 'aria-label': compact ? name : undefined }
  // Nombre à choisir dans une liste (taux de TVA…) : une liste déroulante plutôt qu'une saisie libre
  if (field.choices?.length && ['int', 'decimal', 'money', 'percent'].includes(field.type)) {
    return (
      <select {...common} className={`select ${cls}`} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
        {!field.required || value == null ? <option value="">—</option> : null}
        {field.choices.map((c) => <option key={String(c.value)} value={c.value}>{pick(c.label)}</option>)}
      </select>
    )
  }
  switch (field.type) {
    case 'longtext':
      return <textarea {...common} className="textarea" value={value ?? ''} maxLength={field.maxlength}
        onChange={(e) => onChange(e.target.value)} />
    case 'int':
    case 'decimal':
    case 'money':
    case 'percent':
      return (
        <div className={field.type === 'money' || field.type === 'percent' ? 'input-unit' : undefined}>
          <input {...common} className={`input num mono ${cls}`} inputMode={field.type === 'int' ? 'numeric' : 'decimal'}
            value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
          {field.type === 'money' ? <span className="unit">€</span> : null}
          {field.type === 'percent' ? <span className="unit">%</span> : null}
        </div>
      )
    case 'date':
      return <input {...common} type="date" className={`input ${cls}`} value={value ?? ''} onChange={(e) => onChange(e.target.value || null)} />
    case 'bool':
      return <Toggle id={id} checked={Boolean(value)} label={name} onChange={(v) => !disabled && onChange(v)} />
    case 'enum':
      return (
        <select {...common} className={`select ${cls}`} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
          {!field.required || value == null ? <option value="">{field.required ? t('entity.choose') : '—'}</option> : null}
          {(field.choices || []).map((c) => <option key={String(c.value)} value={c.value}>{pick(c.label)}</option>)}
        </select>
      )
    case 'ref':
      return <RefSelect id={id} refKey={field.ref} value={value ?? null} label={label} disabled={disabled} required={field.required}
        source={entityKey ? `${entityKey}.${field.name}` : undefined} ariaLabel={compact ? name : undefined}
        onChange={(newValue, option) => onChange(newValue, option)} />
    case 'email':
      return <input {...common} type="email" className={`input ${cls}`} value={value ?? ''} maxLength={200} onChange={(e) => onChange(e.target.value)} />
    case 'phone':
      return <input {...common} type="tel" className={`input ${cls}`} value={value ?? ''} maxLength={30} onChange={(e) => onChange(e.target.value)} />
    default:
      return <input {...common} className={`input ${field.type === 'code' ? 'mono' : ''} ${cls}`} value={value ?? ''}
        maxLength={field.maxlength || 200} onChange={(e) => onChange(e.target.value)} />
  }
}
