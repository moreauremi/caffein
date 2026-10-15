// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLanguage } from '../../context/LanguageContext'
import { money } from '../../lib/format'
import { EmptyState, Spinner } from '../ui'
import FieldValue from './FieldValue'

// Vue en colonnes d'une liste, une colonne par statut (Entity.board). Le serveur range les fiches et calcule
// le nombre et le total de chaque colonne : on ne fait que les afficher. Un clic ouvre la fiche.
export default function EntityBoard({ entity, data, error, onOpen, onShowAll }) {
  const { t, pick, language } = useLanguage()
  if (error) return <div className="card flush"><EmptyState title={error.message} /></div>
  if (!data) return <div className="card" style={{ padding: 24 }}><Spinner /></div>

  const field = (name) => entity.fields.find((f) => f.name === name)
  const title = field(entity.title)
  const subtitle = entity.subtitle ? field(entity.subtitle) : null
  const details = entity.fields.filter((f) => f.list && ![entity.title, entity.subtitle, data.field].includes(f.name)).slice(0, 3)
  const canShowAll = Boolean(field(data.field)?.filter)

  return (
    <div className="board">
      {data.columns.map((col) => {
        const more = col.count - col.rows.length
        return (
          <section key={String(col.value)} className="board-col" aria-label={pick(col.label)}>
            <header className="board-col-head">
              <span className={`badge ${col.tone || ''}`}>{pick(col.label)}</span>
              <span className="board-col-count">{col.count}</span>
              {col.amount !== null && col.amount !== undefined ? (
                <span className="mono small board-col-amount" title={pick(data.amount_label)}>{money(col.amount, language)}</span>
              ) : null}
            </header>
            <ul className="board-cards">
              {col.rows.map((row) => (
                <li key={row.id}>
                  <button type="button" className="board-card" onClick={() => onOpen(row.id)}>
                    <span className="board-card-title">{title ? <FieldValue field={title} row={row} link={false} /> : `#${row.id}`}</span>
                    {subtitle ? <span className="small muted truncate"><FieldValue field={subtitle} row={row} link={false} /></span> : null}
                    {details.map((f) => (
                      <span key={f.name} className="board-card-line xsmall">
                        <span className="muted truncate">{pick(f.label)}</span>
                        <FieldValue field={f} row={row} link={false} />
                      </span>
                    ))}
                  </button>
                </li>
              ))}
            </ul>
            {more > 0 && canShowAll ? (
              <button type="button" className="btn sm ghost board-more" onClick={() => onShowAll(col.value)}>
                {t('entity.board_more', { n: more })}
              </button>
            ) : null}
            {more > 0 && !canShowAll ? <p className="xsmall muted board-more">{t('entity.board_more', { n: more })}</p> : null}
            {!col.count ? <p className="xsmall subtle board-empty">{t('entity.board_empty')}</p> : null}
          </section>
        )
      })}
    </div>
  )
}
