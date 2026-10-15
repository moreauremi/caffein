// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useMemo, useState } from 'react'
import { AlertTriangle, Info, Lock, Save, Trash2 } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { buildPayload, initialChildren, initialForm } from '../../lib/entity'
import { useDebounced } from '../../lib/useDebounced'
import NamedIcon from '../NamedIcon'
import { ConfirmButton, Drawer, Spinner } from '../ui'
import FieldInput from './FieldInput'
import FieldValue from './FieldValue'
import LinesEditor from './LinesEditor'

const ACTION_CLASS = { primary: 'btn primary', danger: 'btn danger', default: 'btn' }

// Fiche d'une entité dans un tiroir : création, modification, lignes, actions, suppression.
// Les champs calculés (totaux…) sont recalculés par le serveur pendant la saisie (/preview).
export default function EntityDrawer({ entity, rowId, prefill, onClose, onChanged }) {
  const { t, pick } = useLanguage()
  const toast = useToast()
  const formId = useId()
  const base = `/api/data/${entity.module}/${entity.name}`
  const [id, setId] = useState(rowId || null)
  const [row, setRow] = useState(null)
  const [form, setForm] = useState(() => (rowId ? null : initialForm(entity, null, prefill)))
  const [children, setChildren] = useState(() => (rowId ? null : initialChildren(entity, null)))
  const [snapshot, setSnapshot] = useState(() => (rowId ? null : JSON.stringify([form, children])))
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)
  const [loadError, setLoadError] = useState(null)

  function apply(saved) {
    const f = initialForm(entity, saved)
    const c = initialChildren(entity, saved)
    setRow(saved)
    setForm(f)
    setChildren(c)
    setSnapshot(JSON.stringify([f, c]))
    setPreview(null)
    setError(null)
  }

  useEffect(() => {
    if (!rowId) return undefined
    let cancelled = false
    api.get(`${base}/${rowId}`)
      .then((saved) => !cancelled && apply(saved))
      .catch((err) => !cancelled && setLoadError(err.message))
    return () => { cancelled = true }
  }, [rowId, base]) // eslint-disable-line react-hooks/exhaustive-deps

  const isNew = !id
  const locked = row?._locked || null
  const canEdit = isNew ? entity.can_create : entity.can_edit && !locked
  const dirty = form !== null && JSON.stringify([form, children]) !== snapshot
  const computedFields = entity.fields.filter((f) => f.computed)
  const wantsPreview = canEdit && (computedFields.length > 0 || entity.children.some((c) => c.fields.some((f) => f.computed)))
  const payload = useMemo(() => (form ? buildPayload(entity, form, children) : null), [entity, form, children])
  const debouncedPayload = useDebounced(dirty && wantsPreview ? JSON.stringify(payload) : null, 350)

  // Aperçu des calculs pendant la saisie : c'est le serveur qui calcule
  useEffect(() => {
    if (!debouncedPayload) return undefined
    let cancelled = false
    api.post(`${base}/preview${id ? `?id=${id}` : ''}`, JSON.parse(debouncedPayload))
      .then((result) => !cancelled && setPreview(result))
      .catch(() => {})
    return () => { cancelled = true }
  }, [debouncedPayload, base, id])

  const shownRow = { ...(row || {}), ...(form || {}), ...((dirty && preview?.computed) || {}) }

  function close() {
    if (dirty && !window.confirm(t('entity.discard'))) return
    onClose()
  }

  async function save() {
    setBusy('save')
    setError(null)
    try {
      const saved = isNew ? await api.post(base, payload) : await api.put(`${base}/${id}`, payload)
      apply(saved)
      if (isNew) setId(saved.id)
      onChanged?.(saved, isNew)
      toast(t(isNew ? 'entity.created' : 'entity.saved'))
      return saved
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setBusy('')
    }
  }

  async function runAction(action) {
    setBusy(action.key)
    setError(null)
    try {
      if (dirty && canEdit && !(await save())) return
      const result = await api.post(`${base}/${id}/actions/${action.key}`, {})
      apply(result.row)
      onChanged?.(result.row, false)
      toast(result.message || pick(action.label))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function remove() {
    try {
      await api.del(`${base}/${id}`)
      toast(t('entity.deleted'))
      onChanged?.(null, false)
      onClose()
    } catch (err) {
      setError(err.message)
    }
  }

  const setField = (field) => (value, option) => {
    setForm((f) => {
      const next = { ...f, [field.name]: value }
      if (field.type === 'ref') {
        next[`${field.name}__label`] = option?.label ?? null
        for (const [local, remote] of Object.entries(option?.fill || {})) {
          if (remote !== null && remote !== undefined && local in next) next[local] = remote
        }
      }
      return next
    })
  }

  const titleField = entity.fields.find((f) => f.name === entity.title)
  const title = isNew
    ? t('entity.new_title', { name: pick(entity.label) })
    : (row ? (row[entity.title] || `#${row.id}`) : t('entity.loading'))
  const subtitle = isNew ? pick(entity.description) : pick(entity.label)
  const actions = (entity.actions || []).filter((a) => row?._actions?.includes(a.key))

  const footer = form && (
    <>
      {/* le serveur dit si la fiche se supprime (droits, règle du module : une commande annulée…) */}
      {!isNew && row?._deletable && (
        <ConfirmButton className="btn danger" confirmLabel={t('entity.delete_confirm')} onConfirm={remove}>
          <Trash2 size={15} /> {t('common.delete')}
        </ConfirmButton>
      )}
      <span className="grow" />
      {actions.map((action) => (
        action.confirm ? (
          <ConfirmButton key={action.key} className={ACTION_CLASS[action.style] || 'btn'} confirmLabel={pick(action.confirm)}
            disabled={Boolean(busy)} onConfirm={() => runAction(action)}>
            {action.icon ? <NamedIcon name={action.icon} size={15} /> : null} {pick(action.label)}
          </ConfirmButton>
        ) : (
          <button key={action.key} type="button" className={ACTION_CLASS[action.style] || 'btn'} disabled={Boolean(busy)}
            onClick={() => runAction(action)}>
            {busy === action.key ? <Spinner /> : action.icon ? <NamedIcon name={action.icon} size={15} /> : null} {pick(action.label)}
          </button>
        )
      ))}
      {canEdit && (
        <button type="submit" form={formId} className="btn primary" disabled={Boolean(busy) || (!dirty && !isNew)}>
          {busy === 'save' ? <Spinner /> : <Save size={15} />} {t('common.save')}
        </button>
      )}
    </>
  )

  return (
    <Drawer title={title} subtitle={subtitle} onClose={close} footer={footer}>
      {loadError ? <div className="alert bad"><AlertTriangle size={16} /><span>{loadError}</span></div> : null}
      {!form && !loadError ? <Spinner /> : null}
      {form && (
        <form id={formId} className="stack lg" onSubmit={(e) => { e.preventDefault(); if (canEdit) save() }}>
          {locked ? <div className="alert info small"><Lock size={16} /><span>{locked}</span></div> : null}
          {!isNew && !canEdit && !locked ? <div className="alert info small"><Info size={16} /><span>{t('entity.readonly')}</span></div> : null}
          {error ? <div className="alert bad small" role="alert"><AlertTriangle size={16} /><span>{error}</span></div> : null}
          <div className="form-grid">
            {entity.fields.map((field) => {
              const inputId = `${formId}-${field.name}`
              if (field.readonly) {
                // Champ rempli par le serveur (numéro, statut, total) : affiché, jamais saisi
                if (isNew && (!field.computed || shownRow[field.name] === '' || shownRow[field.name] == null)) return null
                if (field === titleField && !isNew) return null
                return (
                  <div key={field.name} className={`field ${field.width === 'full' ? 'full' : ''}`}>
                    <span className="label">{pick(field.label)}</span>
                    <div className="field-static"><FieldValue field={field} row={shownRow} /></div>
                  </div>
                )
              }
              return (
                <div key={field.name} className={`field ${field.width === 'full' || field.type === 'longtext' ? 'full' : ''} ${field.type === 'bool' ? 'field-inline' : ''}`}>
                  <label htmlFor={inputId}>{pick(field.label)}{field.required && canEdit ? ' *' : ''}</label>
                  {canEdit ? (
                    <FieldInput id={inputId} field={field} value={form[field.name]} label={form[`${field.name}__label`]}
                      entityKey={entity.key} onChange={setField(field)} />
                  ) : <div className="field-static"><FieldValue field={field} row={shownRow} /></div>}
                  {field.help ? <span className="hint">{pick(field.help)}</span> : null}
                </div>
              )
            })}
          </div>
          {entity.children.map((child) => (
            <LinesEditor key={child.key} child={child} lines={children[child.key] || []} entityKey={entity.key} disabled={!canEdit}
              computed={dirty && preview?.children?.[child.key] ? preview.children[child.key] : (row?.[child.key] || [])}
              onChange={(lines) => setChildren((c) => ({ ...c, [child.key]: lines }))} />
          ))}
          {dirty && canEdit ? <p className="xsmall subtle">{t('entity.unsaved')}</p> : null}
        </form>
      )}
    </Drawer>
  )
}
