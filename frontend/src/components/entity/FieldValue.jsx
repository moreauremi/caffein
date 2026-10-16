// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from 'react-router-dom'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { date, money, number } from '../../lib/format'

// Valeur d'un champ, telle que calculée et renvoyée par le serveur : l'interface ne fait que la mettre en forme.
export default function FieldValue({ field, row, link = true }) {
  const { t, pick, language } = useLanguage()
  const { entityPath } = useMeta()
  const value = row?.[field.name]
  if (value === null || value === undefined || value === '') {
    return <span className="subtle">—</span>
  }
  switch (field.type) {
    case 'money':
      return <span className="mono nowrap">{money(value, language)}</span>
    case 'decimal':
      return <span className="mono">{number(value, language, 3)}</span>
    case 'int':
      return <span className="mono">{number(value, language)}</span>
    case 'percent':
      return <span className="mono nowrap">{number(value, language, 2)} %</span>
    case 'date':
      return <span className="nowrap">{date(value, language)}</span>
    case 'bool':
      return <span className={`badge ${value ? 'good' : 'outline'}`}>{value ? t('entity.yes') : t('entity.no')}</span>
    case 'enum': {
      const choice = (field.choices || []).find((c) => String(c.value) === String(value))
      if (!choice) return <span>{String(value)}</span>
      return <span className={`badge ${choice.tone || ''}`}>{pick(choice.label)}</span>
    }
    case 'ref': {
      const label = row[`${field.name}__label`] ?? `#${value}`
      const path = link ? entityPath(field.ref) : null
      return path
        ? <Link className="link-plain" to={`${path}?id=${value}`} onClick={(e) => e.stopPropagation()}>{label}</Link>
        : <span>{label}</span>
    }
    case 'email':
      return <span className="truncate">{value}</span>
    case 'code':
      return <span className="mono nowrap">{value}</span>
    case 'longtext':
      return <span className="pre-line">{value}</span>
    default:
      return <span>{String(value)}</span>
  }
}
