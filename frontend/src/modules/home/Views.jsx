// SPDX-License-Identifier: AGPL-3.0-or-later
// « Mes vues » : l'utilisateur dit ce qu'il veut voir, la page se compose.
// L'IA (ou l'analyse locale) ne renvoie qu'une description de la vue ; le serveur la valide
// et calcule les données. Une vue enregistrée se recharge sans rappeler l'IA.
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Bot, Cpu, LayoutGrid, RotateCw, Save, Sparkles, Trash2, WandSparkles } from 'lucide-react'
import Widget from './Widget'
import { ConfirmButton, EmptyState, Spinner } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { useApi } from '../../lib/useApi'
import { readCurrentView, storeCurrentView } from '../../lib/viewsStorage'

const EMPTY = { title: '', widgets: [] }
const EXAMPLES = ['views.example_1', 'views.example_2', 'views.example_3', 'views.example_4', 'views.example_5']

// Description d'une vue, sans les données (ce qu'on envoie, enregistre ou garde dans le navigateur)
const toSpec = (view) => ({
  title: view?.title || '',
  widgets: (view?.widgets || []).map(({ source, visual, title, params }) => ({ source, visual, title, params })),
})
const widgetKeys = (view) => toSpec(view).widgets.map((w) => JSON.stringify(w))
const sameWidgets = (a, b) => JSON.stringify(widgetKeys(a)) === JSON.stringify(widgetKeys(b))
const sharesWidget = (a, b) => widgetKeys(a).some((key) => widgetKeys(b).includes(key))

export default function Views() {
  const { t, language } = useLanguage()
  const { user } = useAuth()
  const toast = useToast()
  const inputRef = useRef(null)
  const saveButtonRef = useRef(null)
  const gridRef = useRef(null)
  const seq = useRef(0)              // numéro de la dernière action : une réponse plus ancienne est ignorée
  const refocus = useRef(null)       // élément à focaliser une fois l'action terminée
  const [stored] = useState(() => readCurrentView(user?.id))
  const [text, setText] = useState('')
  // null : la dernière vue affichée est en cours de recalcul
  const [view, setView] = useState(() => (stored?.spec?.widgets?.length ? null : EMPTY))
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const [activeId, setActiveId] = useState(() => stored?.activeId ?? null)
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const { data: listing, error: listError, loading: listLoading, reload: reloadList, setData: setListing } = useApi('/api/dashboards')
  const saved = listing?.views || []
  const ai = listing?.ai
  const locked = busy || view === null

  const show = (next, id = activeId) => {
    setView(next)
    storeCurrentView(user?.id, { spec: toSpec(next), activeId: id })
  }

  // La dernière vue affichée est recalculée sans IA (sauf si l'utilisateur a déjà fait autre chose)
  useEffect(() => {
    if (!stored?.spec?.widgets?.length) return undefined
    const mine = seq.current
    api.post('/api/dashboards/render', { spec: stored.spec })
      .then((data) => seq.current === mine && setView(data))
      .catch(() => seq.current === mine && setView(EMPTY))
    return undefined
  }, [stored])

  // Après une action, le focus revient où l'utilisateur en a besoin (le champ, ou la carte voisine)
  useEffect(() => {
    if (busy || refocus.current === null) return  // 0 est un indice de carte valide
    const target = refocus.current
    refocus.current = null
    if (target === 'input') inputRef.current?.focus()
    else if (target === 'save') saveButtonRef.current?.focus()
    else if (typeof target === 'number') {
      const buttons = gridRef.current?.querySelectorAll('.widget-remove') || []
      ;(buttons[Math.min(target, buttons.length - 1)] || inputRef.current)?.focus()
    }
  })

  // La vue enregistrée « active » n'est plus active si l'écran ne lui ressemble plus du tout
  const active = saved.find((v) => v.id === activeId)
  const modified = active && view && !sameWidgets(view, active.spec)

  const compose = async (request) => {
    const demand = (request ?? text).trim()
    if (demand.length < 3 || locked) return
    const mine = ++seq.current
    setBusy(true)
    try {
      const res = await api.post('/api/dashboards/compose', { text: demand, spec: toSpec(view), language })
      if (seq.current !== mine) return
      // Une vue entièrement remplacée n'est plus la vue enregistrée : on ne propose plus de l'écraser
      const nextId = active && sharesWidget(res.view, active.spec) ? activeId : null
      setActiveId(nextId)
      show(res.view, nextId)
      setFeedback({
        ok: res.understood,
        text: res.reply || t(`views.msg.${res.message || (res.understood ? 'composed' : 'not_understood')}`),
        by: res.composed_by,
      })
      if (res.understood) setText('')
    } catch (error) {
      if (seq.current === mine) setFeedback({ ok: false, text: error.message, by: null })
    } finally {
      if (seq.current === mine) {
        refocus.current = 'input'
        setBusy(false)
      }
    }
  }

  const remove = (index) => {
    if (locked) return
    seq.current += 1
    refocus.current = view.widgets.length > 1 ? index : 'input'
    show({ ...view, widgets: view.widgets.filter((_, i) => i !== index) })
  }

  const open = async (id) => {
    if (locked) return
    const mine = ++seq.current
    setBusy(true)
    try {
      const data = await api.get(`/api/dashboards/${id}`)
      if (seq.current !== mine) return
      setActiveId(id)
      show(data.view, id)
      setFeedback(null)
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      if (seq.current === mine) setBusy(false)
    }
  }

  const save = async (event) => {
    event.preventDefault()
    if (saving || !name.trim()) return
    setSaving(true)
    try {
      const created = await api.post('/api/dashboards', { name, spec: toSpec(view) })
      setListing((d) => ({ ...d, views: [...(d?.views || []), created] }))
      setActiveId(created.id)
      storeCurrentView(user?.id, { spec: toSpec(view), activeId: created.id })
      setNaming(false)
      setName('')
      refocus.current = 'save'
      toast(t('views.saved', { name: created.name }))
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const update = async () => {
    if (saving) return
    setSaving(true)
    try {
      const updated = await api.put(`/api/dashboards/${activeId}`, { spec: toSpec(view) })
      setListing((d) => ({ ...d, views: d.views.map((v) => (v.id === updated.id ? updated : v)) }))
      toast(t('views.updated', { name: updated.name }))
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const destroy = async () => {
    try {
      await api.del(`/api/dashboards/${activeId}`)
      setListing((d) => ({ ...d, views: d.views.filter((v) => v.id !== activeId) }))
      setActiveId(null)
      storeCurrentView(user?.id, { spec: toSpec(view), activeId: null })
      toast(t('views.deleted'))
    } catch (error) {
      toast(error.message, 'error')
    }
  }

  const widgets = view?.widgets || []

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('views.title')}</h1>
          <p className="page-sub">{t('views.subtitle')}</p>
        </div>
        {ai && (
          <span className={`badge ${ai.enabled ? 'accent' : 'outline'}`} aria-describedby="views-mode-help">
            {ai.enabled ? <Sparkles /> : <Cpu />}
            {t(ai.enabled ? 'views.mode_ai' : 'views.mode_offline')}
            <span id="views-mode-help" className="sr-only">{t(ai.enabled ? 'views.mode_ai_help' : 'views.mode_offline_help')}</span>
          </span>
        )}
      </div>

      <form className="card ask" onSubmit={(e) => { e.preventDefault(); compose() }}>
        <label htmlFor="ask-input" className="sr-only">{t('views.ask_label')}</label>
        <div className="ask-row">
          <WandSparkles size={20} className="ask-icon" aria-hidden="true" />
          {/* readOnly plutôt que disabled pendant la requête : le focus reste dans le champ */}
          <input id="ask-input" ref={inputRef} className="ask-input" value={text} maxLength={500} autoComplete="off"
            placeholder={t('views.ask_placeholder')} onChange={(e) => setText(e.target.value)} readOnly={locked}
            aria-busy={locked} />
          <button type="submit" className="btn primary" disabled={locked || text.trim().length < 3}>
            {busy ? <Spinner /> : <Sparkles size={16} />} {t('views.ask_button')}
          </button>
        </div>
        <div className="chips ask-examples" role="group" aria-label={t('views.examples')}>
          {EXAMPLES.map((key) => (
            <button key={key} type="button" className="chip" disabled={locked} onClick={() => compose(t(key))}>{t(key)}</button>
          ))}
        </div>
      </form>

      {/* Zone annoncée aux lecteurs d'écran : toujours présente, seul son contenu change */}
      <div role="status" aria-live="polite" className="ask-feedback-zone">
        {feedback && (
          <div className={`alert ${feedback.ok ? 'info' : 'warn'} ask-feedback`}>
            <Bot size={18} />
            <span className="grow">{feedback.text}</span>
            {feedback.by && <span className="xsmall muted">{t(feedback.by === 'claude' ? 'views.by_ai' : 'views.by_local')}</span>}
          </div>
        )}
      </div>

      <div className="row between wrap views-bar">
        <div className="views-saved">
          {listError ? (
            <div className="row small" style={{ color: 'var(--bad)' }}>
              <AlertTriangle size={15} /> {t('views.load_error')}
              <button type="button" className="btn sm ghost" onClick={reloadList}><RotateCw size={14} /> {t('views.retry')}</button>
            </div>
          ) : saved.length ? (
            <div className="chips" role="group" aria-label={t('views.saved_views')}>
              {saved.map((v) => (
                <button key={v.id} type="button" aria-pressed={v.id === activeId} title={v.name}
                  className={`chip view-chip ${v.id === activeId ? 'active' : ''}`} onClick={() => open(v.id)} disabled={locked}>
                  <LayoutGrid size={14} /> <span className="view-chip-name">{v.name}</span>
                </button>
              ))}
            </div>
          ) : !listLoading && <span className="small muted">{t('views.no_saved')}</span>}
        </div>
        {widgets.length > 0 && (
          <div className="row wrap">
            {modified && (
              <button type="button" className="btn sm" onClick={update} disabled={saving}
                aria-label={t('views.update', { name: active.name })} title={t('views.update', { name: active.name })}>
                <Save size={15} /> {t('views.update_short')}
              </button>
            )}
            {active && (
              <ConfirmButton className="btn sm ghost danger" confirmLabel={t('common.confirm_delete')} onConfirm={destroy}>
                <Trash2 size={15} /> {t('views.delete_view')}
              </ConfirmButton>
            )}
            {naming ? (
              <form className="row" onSubmit={save}>
                <input className="input sm" autoFocus value={name} maxLength={80} placeholder={t('views.name_placeholder')}
                  aria-label={t('views.name_label')} onChange={(e) => setName(e.target.value)} />
                <button type="submit" className="btn sm primary" disabled={saving || !name.trim()}>
                  {saving && <Spinner />} {t('common.save')}
                </button>
                <button type="button" className="btn sm ghost" onClick={() => { refocus.current = 'save'; setNaming(false) }}>
                  {t('common.cancel')}
                </button>
              </form>
            ) : (
              <button type="button" ref={saveButtonRef} className="btn sm" onClick={() => setNaming(true)}>
                <Save size={15} /> {t('views.save')}
              </button>
            )}
          </div>
        )}
      </div>

      {view === null ? (
        <div className="card"><Spinner /></div>
      ) : widgets.length ? (
        <div className="widget-grid" ref={gridRef}>
          {widgets.map((w, i) => (
            <Widget key={`${w.source}-${w.visual}-${JSON.stringify(w.params)}`} widget={w} onRemove={() => remove(i)}
              disabled={locked} />
          ))}
        </div>
      ) : (
        <div className="card">
          <EmptyState icon={Sparkles} title={t('views.empty_title')}>{t('views.empty_text')}</EmptyState>
        </div>
      )}

      <p className="xsmall muted views-note">{t('views.privacy')}</p>
    </div>
  )
}
