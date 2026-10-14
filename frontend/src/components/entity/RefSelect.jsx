// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useRef, useState } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { api } from '../../lib/api'
import { useDebounced } from '../../lib/useDebounced'
import { Spinner } from '../ui'

// Choix d'une fiche d'une autre entité (client, article…), avec recherche côté serveur.
// `source` (« sales.orders.client_id ») autorise la liste depuis le formulaire qui fait référence et
// renvoie les valeurs à recopier (`fill`) avec chaque choix.
export default function RefSelect({ refKey, value, label, onChange, source, disabled = false, required = false, id, ariaLabel, invalid, placeholder }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState(null)
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(false)
  const debounced = useDebounced(query, 200)
  const wrapper = useRef(null)
  const input = useRef(null)
  const listId = useId()
  const [module, name] = (refKey || '').split('.')

  useEffect(() => {
    if (!open) return undefined
    let cancelled = false
    const params = new URLSearchParams()
    if (debounced) params.set('q', debounced)
    if (source) params.set('for', source)
    Promise.resolve().then(() => !cancelled && setLoading(true))
    api.get(`/api/data/${module}/${name}/options?${params}`)
      .then((rows) => { if (!cancelled) { setOptions(rows); setActive(0) } })
      .catch(() => !cancelled && setOptions([]))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [open, debounced, module, name, source])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => !wrapper.current?.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function choose(option) {
    onChange(option ? option.id : null, option)
    setOpen(false)
    setQuery('')
    input.current?.focus()
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) return setOpen(true)
      setActive((i) => Math.min(i + 1, (options?.length || 1) - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && open) {
      e.preventDefault()
      if (options?.[active]) choose(options[active])
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation()
      setOpen(false)
    }
  }

  const shown = open ? query : (label ?? (value ? `#${value}` : ''))
  return (
    <div className={`refselect ${disabled ? 'disabled' : ''}`} ref={wrapper}>
      <input ref={input} id={id} className={`input ${invalid ? 'invalid' : ''}`} value={shown} disabled={disabled}
        placeholder={open ? (label || t('entity.search')) : (placeholder || t('entity.choose'))} autoComplete="off"
        role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list" aria-label={ariaLabel}
        aria-activedescendant={open && options?.[active] ? `${listId}-${active}` : undefined}
        onFocus={() => !disabled && setOpen(true)} onClick={() => !disabled && setOpen(true)}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }} onKeyDown={onKeyDown} />
      <span className="refselect-icons">
        {loading && open ? <Spinner size={13} /> : null}
        {value && !required && !disabled ? (
          <button type="button" className="icon-btn xs" aria-label={t('common.delete')} onClick={() => choose(null)}><X size={14} /></button>
        ) : <ChevronDown size={15} aria-hidden="true" />}
      </span>
      {open && (
        <ul className="refselect-list" role="listbox" id={listId}>
          {options === null ? <li className="refselect-empty">{t('entity.loading')}</li> : null}
          {options?.length === 0 ? <li className="refselect-empty">{t('entity.no_option')}</li> : null}
          {options?.map((option, i) => (
            <li key={option.id} id={`${listId}-${i}`} role="option" aria-selected={option.id === value}
              className={`${i === active ? 'active' : ''} ${option.id === value ? 'selected' : ''}`}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); choose(option) }}>
              <span className="truncate">{option.label || `#${option.id}`}</span>
              {option.sublabel ? <span className="xsmall muted truncate">{option.sublabel}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
