// SPDX-License-Identifier: AGPL-3.0-or-later
import { Plus, Trash2 } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { blankLine } from '../../lib/entity'
import FieldInput from './FieldInput'
import FieldValue from './FieldValue'

const NUMERIC = ['int', 'decimal', 'money', 'percent']

// Lignes rattachées à une fiche (lignes de commande, composants…). Les colonnes calculées (montants)
// viennent du serveur (`computed`, une entrée par ligne) : rien n'est calculé ici.
export default function LinesEditor({ child, lines, computed, onChange, entityKey, disabled: locked = false }) {
  const { t, pick } = useLanguage()
  const editable = child.fields.filter((f) => !f.readonly)
  const disabled = locked || child.writable === false || editable.length === 0
  const shown = child.fields

  function setLine(index, name, value, option) {
    onChange(lines.map((line, i) => {
      if (i !== index) return line
      const next = { ...line, [name]: value, [`${name}__label`]: option?.label ?? (value == null ? null : line[`${name}__label`]) }
      // Choix d'une fiche qui recopie des valeurs (article → désignation, prix)
      for (const [local, remote] of Object.entries(option?.fill || {})) {
        if (remote !== null && remote !== undefined) next[local] = remote
      }
      return next
    }))
  }

  const remove = (index) => onChange(lines.filter((_, i) => i !== index))
  const add = () => onChange([...lines, blankLine(child)])

  return (
    <div className="lines">
      <div className="row between" style={{ marginBottom: 8 }}>
        <div className="label">{pick(child.label)}</div>
        <span className="xsmall muted">{lines.length ? t('entity.lines_count', { n: lines.length }) : null}</span>
      </div>
      {lines.length ? (
        <div className="table-wrap lines-wrap">
          <table className="table lines-table">
            <thead>
              <tr>
                {shown.map((f) => (
                  <th key={f.name} className={NUMERIC.includes(f.type) ? 'right' : undefined}
                    title={f.computed ? t('entity.computed') : undefined}>
                    {pick(f.label)}{f.required && !f.readonly && !disabled ? ' *' : ''}
                  </th>
                ))}
                {!disabled && <th aria-label={t('entity.actions')} />}
              </tr>
            </thead>
            <tbody>
              {lines.map((line, i) => (
                <tr key={i}>
                  {shown.map((f) => (
                    <td key={f.name} className={`lines-cell lines-${f.type} ${NUMERIC.includes(f.type) ? 'right' : ''}`}>
                      {f.readonly || disabled
                        ? <FieldValue field={f} row={{ ...line, ...(computed?.[i] || {}) }} link={false} />
                        : <FieldInput compact field={f} value={line[f.name]} label={line[`${f.name}__label`]} entityKey={entityKey}
                            onChange={(v, option) => setLine(i, f.name, v, option)} />}
                    </td>
                  ))}
                  {!disabled && (
                    <td className="lines-remove">
                      <button type="button" className="icon-btn" aria-label={t('entity.remove_line', { n: i + 1 })} onClick={() => remove(i)}>
                        <Trash2 size={15} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="small muted">{t('entity.no_lines')}</p>}
      {!disabled && editable.length > 0 && (
        <button type="button" className="btn sm ghost" style={{ marginTop: 8 }} onClick={add}>
          <Plus size={15} /> {t('entity.add_line')}
        </button>
      )}
    </div>
  )
}
