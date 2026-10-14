// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Plus, Search, X } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { useMeta } from '../../context/MetaContext'
import { useApi } from '../../lib/useApi'
import { useDebounced } from '../../lib/useDebounced'
import NamedIcon from '../NamedIcon'
import { EmptyState, Spinner } from '../ui'
import EntityDrawer from './EntityDrawer'
import FieldValue from './FieldValue'
import RefSelect from './RefSelect'

const PAGE_SIZE = 50
const NUMERIC = ['int', 'decimal', 'money', 'percent']

// Export tableur : mêmes recherche, filtres et tri que la liste affichée, toutes les pages
function exportQuery(listQuery, language) {
  const query = new URLSearchParams(listQuery)
  query.delete('size')
  query.delete('page')
  query.set('lang', language)
  return query.toString()
}

// Écran généré pour une entité déclarée par un module : liste (recherche, filtres, tri, pages) et fiche.
// L'état est dans l'adresse (?q=…&f_status=…&sort=…&id=12) : on peut partager un lien vers une fiche ou une liste filtrée.
export default function EntityPage({ entityKey }) {
  const { t, pick } = useLanguage()
  const { entity: entityMeta } = useMeta()
  const entity = entityMeta(entityKey)
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') || '')
  const debouncedSearch = useDebounced(search, 300)

  const update = (changes) => setParams((current) => {
    const next = new URLSearchParams(current)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === undefined || value === '') next.delete(key)
      else next.set(key, value)
    }
    return next
  }, { replace: true })

  useEffect(() => {
    if ((params.get('q') || '') !== debouncedSearch) update({ q: debouncedSearch, page: null })
  }, [debouncedSearch]) // eslint-disable-line react-hooks/exhaustive-deps

  const listQuery = useMemo(() => {
    const query = new URLSearchParams({ size: String(PAGE_SIZE) })
    for (const [key, value] of params) {
      if (key === 'q' || key === 'sort' || key === 'dir' || key === 'page' || key.startsWith('f_')) query.set(key, value)
    }
    return query.toString()
  }, [params])
  const list = useApi(entity ? `/api/data/${entity.module}/${entity.name}?${listQuery}` : null)
  const { language } = useLanguage()

  if (!entity) return <EmptyState title={t('nav.no_access')} />

  const columns = entity.fields.filter((f) => f.list)
  const filters = entity.fields.filter((f) => f.filter)
  const activeFilters = filters.filter((f) => params.get(`f_${f.name}`) !== null)
  const sort = params.get('sort')
  const dir = params.get('dir') || 'asc'
  const page = Number(params.get('page') || 1)
  const data = list.data
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const openId = params.get('id')
  const creating = params.get('new') !== null
  // Préremplissage d'une création depuis l'adresse (?new=1&client_id=3)
  const prefill = creating
    ? Object.fromEntries(entity.fields.filter((f) => !f.readonly && params.get(f.name) !== null).map((f) => [f.name, params.get(f.name)]))
    : {}

  function toggleSort(field) {
    if (sort === field.name) update({ dir: dir === 'asc' ? 'desc' : 'asc', page: null })
    else update({ sort: field.name, dir: 'asc', page: null })
  }

  function closeDrawer() {
    const next = { id: null, new: null }
    for (const f of entity.fields) next[f.name] = null
    update(next)
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title row" style={{ gap: 10 }}>
            {entity.icon ? <span className="title-icon"><NamedIcon name={entity.icon} size={20} /></span> : null}
            {pick(entity.plural)}
          </h1>
          {entity.description ? <p className="page-sub">{pick(entity.description)}</p> : null}
        </div>
        {entity.can_create && (
          <button type="button" className="btn primary" onClick={() => update({ new: '1', id: null })}>
            <Plus size={16} /> {t('entity.new')}
          </button>
        )}
      </div>

      <div className="entity-toolbar">
        <div className="input-icon grow" style={{ minWidth: 200, maxWidth: 360 }}>
          <Search size={16} />
          <input className="input" type="search" value={search} placeholder={t('entity.search')} aria-label={t('entity.search')}
            onChange={(e) => setSearch(e.target.value)} />
        </div>
        {filters.map((field) => {
          const value = params.get(`f_${field.name}`)
          const label = pick(field.label)
          if (field.type === 'ref') {
            return (
              <div key={field.name} className="entity-filter">
                <RefSelect refKey={field.ref} value={value ? Number(value) : null} label={params.get(`l_${field.name}`)} ariaLabel={label}
                  placeholder={`${label} · ${t('entity.all')}`}
                  onChange={(id, option) => update({ [`f_${field.name}`]: id, [`l_${field.name}`]: option?.label, page: null })} />
              </div>
            )
          }
          const choices = field.type === 'bool'
            ? [{ value: '1', label: t('entity.yes') }, { value: '0', label: t('entity.no') }]
            : (field.choices || []).map((c) => ({ value: String(c.value), label: pick(c.label) }))
          return (
            <select key={field.name} className="select entity-filter" aria-label={label} value={value ?? ''}
              onChange={(e) => update({ [`f_${field.name}`]: e.target.value, page: null })}>
              <option value="">{label} · {t('entity.all')}</option>
              {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          )
        })}
        {(activeFilters.length > 0 || params.get('q')) && (
          <button type="button" className="btn sm ghost" onClick={() => {
            setSearch('')
            update({ q: null, page: null, ...Object.fromEntries(filters.flatMap((f) => [[`f_${f.name}`, null], [`l_${f.name}`, null]])) })
          }}>
            <X size={14} /> {t('entity.clear_filters')}
          </button>
        )}
        <span className="grow" />
        {data ? <span className="small muted">{t('entity.count', { n: data.total })}</span> : null}
        {data?.total ? (
          <a className="btn sm ghost" title={t('entity.export_hint')} download
            href={`/api/data/${entity.module}/${entity.name}/export?${exportQuery(listQuery, language)}`}>
            <Download size={14} /> {t('entity.export')}
          </a>
        ) : null}
      </div>

      <div className="card flush">
        {list.error ? <EmptyState title={list.error.message} /> : null}
        {!data && !list.error ? <div style={{ padding: 24 }}><Spinner /></div> : null}
        {data && data.rows.length === 0 ? (
          <EmptyState icon={entity.icon ? (props) => <NamedIcon name={entity.icon} {...props} /> : undefined}
            title={params.get('q') || activeFilters.length ? t('entity.empty_search') : t('entity.empty')}>
            {entity.can_create && !params.get('q') && !activeFilters.length ? (
              <button type="button" className="btn sm" style={{ marginTop: 8 }} onClick={() => update({ new: '1' })}>
                <Plus size={14} /> {t('entity.create_first')}
              </button>
            ) : null}
          </EmptyState>
        ) : null}
        {data && data.rows.length > 0 ? (
          <div className="table-wrap">
            <table className={`table entity-table ${list.loading ? 'is-loading' : ''}`}>
              <thead>
                <tr>
                  {columns.map((field) => {
                    const sorted = sort === field.name
                    const label = pick(field.label)
                    return (
                      <th key={field.name} className={NUMERIC.includes(field.type) ? 'right' : undefined}
                        aria-sort={sorted ? (dir === 'asc' ? 'ascending' : 'descending') : undefined}>
                        {field.sortable ? (
                          <button type="button" className="th-sort" onClick={() => toggleSort(field)} title={t('entity.sort_by', { name: label })}>
                            {label}
                            {sorted ? (dir === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />) : null}
                          </button>
                        ) : label}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} className="clickable" onClick={() => update({ id: row.id, new: null })}>
                    {columns.map((field, i) => (
                      <td key={field.name} className={NUMERIC.includes(field.type) ? 'right' : undefined}>
                        {i === 0 ? (
                          <button type="button" className="row-open" onClick={(e) => { e.stopPropagation(); update({ id: row.id, new: null }) }}>
                            <FieldValue field={field} row={row} link={false} />
                          </button>
                        ) : <FieldValue field={field} row={row} />}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {data && pages > 1 && (
        <div className="row end" style={{ marginTop: 12 }}>
          <span className="small muted">{t('entity.page', { page, pages })}</span>
          <button type="button" className="icon-btn bordered" disabled={page <= 1} aria-label={t('entity.prev')}
            onClick={() => update({ page: page - 1 > 1 ? page - 1 : null })}><ChevronLeft size={16} /></button>
          <button type="button" className="icon-btn bordered" disabled={page >= pages} aria-label={t('entity.next')}
            onClick={() => update({ page: page + 1 })}><ChevronRight size={16} /></button>
        </div>
      )}

      {(openId || creating) && (
        <EntityDrawer key={openId || 'new'} entity={entity} rowId={openId ? Number(openId) : null} prefill={prefill}
          onClose={closeDrawer}
          onChanged={(row, created) => {
            list.reload()
            if (created && row) update({ id: row.id, new: null })
          }} />
      )}
    </div>
  )
}
