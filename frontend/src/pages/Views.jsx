// SPDX-License-Identifier: AGPL-3.0-or-later
// « Mes vues » : l'utilisateur dit ce qu'il veut voir, la page se compose.
// L'IA (ou l'analyse locale) ne renvoie qu'une description de la vue ; le serveur la valide
// et calcule les données. Une vue enregistrée se recharge sans rappeler l'IA.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Cpu, LayoutGrid, Save, Sparkles, Trash2, WandSparkles } from 'lucide-react'
import Widget from '../components/views/Widget'
import { ConfirmButton, EmptyState, Spinner } from '../components/ui'
import { useLanguage } from '../context/LanguageContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'

const STORAGE_KEY = 'caffein.views.current'
const EMPTY = { title: '', widgets: [] }
const EXAMPLES = ['views.example_1', 'views.example_2', 'views.example_3', 'views.example_4', 'views.example_5']

// Description d'une vue, sans les données (ce qu'on envoie, enregistre ou garde dans le navigateur)
const toSpec = (view) => ({
  title: view?.title || '',
  widgets: (view?.widgets || []).map(({ source, visual, title, params }) => ({ source, visual, title, params })),
})

function readStored() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
  } catch {
    return null
  }
}

function store(spec) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(spec))
  } catch {
    /* stockage indisponible (navigation privée…) : la vue n'est simplement pas gardée */
  }
}

export default function Views() {
  const { t, language } = useLanguage()
  const toast = useToast()
  const inputRef = useRef(null)
  const [text, setText] = useState('')
  // null : la dernière vue affichée est en cours de recalcul
  const [view, setView] = useState(() => (readStored()?.widgets?.length ? null : EMPTY))
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const [saved, setSaved] = useState([])
  const [ai, setAi] = useState(null)
  const [activeId, setActiveId] = useState(null)
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')

  const show = useCallback((next, { keep = true } = {}) => {
    setView(next)
    if (keep) store(toSpec(next))
  }, [])

  // Au chargement : vues enregistrées, mode IA, et la dernière vue affichée (recalculée sans IA)
  useEffect(() => {
    let cancelled = false
    api.get('/api/dashboards').then((data) => {
      if (cancelled) return
      setSaved(data.views)
      setAi(data.ai)
    }).catch(() => {})
    const stored = readStored()
    if (stored?.widgets?.length) {
      api.post('/api/dashboards/render', { spec: stored })
        .then((data) => !cancelled && setView(data))
        .catch(() => !cancelled && setView(EMPTY))
    }
    return () => { cancelled = true }
  }, [])

  const compose = async (request) => {
    const demand = (request ?? text).trim()
    if (demand.length < 3 || busy) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await api.post('/api/dashboards/compose', { text: demand, spec: toSpec(view), language })
      show(res.view)
      setFeedback({
        ok: res.understood,
        text: res.reply || t(`views.msg.${res.message}`),
        by: res.composed_by,
      })
      if (res.understood) setText('')
    } catch (error) {
      setFeedback({ ok: false, text: error.message, by: null })
    } finally {
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  const remove = (index) => {
    const widgets = view.widgets.filter((_, i) => i !== index)
    show({ ...view, widgets })
  }

  const open = async (id) => {
    setBusy(true)
    try {
      const data = await api.get(`/api/dashboards/${id}`)
      show(data.view)
      setActiveId(id)
      setFeedback(null)
    } catch (error) {
      toast(error.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const save = async (event) => {
    event.preventDefault()
    try {
      const created = await api.post('/api/dashboards', { name, spec: toSpec(view) })
      setSaved((list) => [...list, created])
      setActiveId(created.id)
      setNaming(false)
      setName('')
      toast(t('views.saved', { name: created.name }))
    } catch (error) {
      toast(error.message, 'error')
    }
  }

  const update = async () => {
    try {
      const updated = await api.put(`/api/dashboards/${activeId}`, { spec: toSpec(view) })
      setSaved((list) => list.map((v) => (v.id === updated.id ? updated : v)))
      toast(t('views.updated', { name: updated.name }))
    } catch (error) {
      toast(error.message, 'error')
    }
  }

  const destroy = async () => {
    try {
      await api.del(`/api/dashboards/${activeId}`)
      setSaved((list) => list.filter((v) => v.id !== activeId))
      setActiveId(null)
      toast(t('views.deleted'))
    } catch (error) {
      toast(error.message, 'error')
    }
  }

  const widgets = view?.widgets || []
  const active = saved.find((v) => v.id === activeId)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('views.title')}</h1>
          <p className="page-sub">{t('views.subtitle')}</p>
        </div>
        {ai && (
          <span className={`badge ${ai.enabled ? 'accent' : 'outline'}`} title={t(ai.enabled ? 'views.mode_ai_help' : 'views.mode_offline_help')}>
            {ai.enabled ? <Sparkles /> : <Cpu />}
            {t(ai.enabled ? 'views.mode_ai' : 'views.mode_offline')}
          </span>
        )}
      </div>

      <form className="card ask" onSubmit={(e) => { e.preventDefault(); compose() }}>
        <label htmlFor="ask-input" className="sr-only">{t('views.ask_label')}</label>
        <div className="ask-row">
          <WandSparkles size={20} className="ask-icon" aria-hidden="true" />
          <input id="ask-input" ref={inputRef} className="ask-input" value={text} maxLength={500} autoComplete="off"
            placeholder={t('views.ask_placeholder')} onChange={(e) => setText(e.target.value)} disabled={busy} />
          <button type="submit" className="btn primary" disabled={busy || text.trim().length < 3}>
            {busy ? <Spinner /> : <Sparkles size={16} />} {t('views.ask_button')}
          </button>
        </div>
        <div className="chips ask-examples" aria-label={t('views.examples')}>
          {EXAMPLES.map((key) => (
            <button key={key} type="button" className="chip" disabled={busy} onClick={() => compose(t(key))}>{t(key)}</button>
          ))}
        </div>
      </form>

      {feedback && (
        <div className={`alert ${feedback.ok ? 'info' : 'warn'} ask-feedback`} role="status">
          <Bot size={18} />
          <span className="grow">{feedback.text}</span>
          {feedback.by && <span className="xsmall muted">{t(feedback.by === 'claude' ? 'views.by_ai' : 'views.by_local')}</span>}
        </div>
      )}

      <div className="row between wrap views-bar">
        <div className="chips" role="tablist" aria-label={t('views.saved_views')}>
          {saved.map((v) => (
            <button key={v.id} type="button" role="tab" aria-selected={v.id === activeId}
              className={`chip ${v.id === activeId ? 'active' : ''}`} onClick={() => open(v.id)} disabled={busy}>
              <LayoutGrid size={14} /> {v.name}
            </button>
          ))}
          {!saved.length && <span className="small muted">{t('views.no_saved')}</span>}
        </div>
        {widgets.length > 0 && (
          <div className="row wrap">
            {active && <button type="button" className="btn sm" onClick={update}><Save size={15} /> {t('views.update', { name: active.name })}</button>}
            {active && <ConfirmButton className="btn sm ghost danger" confirmLabel={t('common.confirm_delete')} onConfirm={destroy}><Trash2 size={15} /> {t('common.delete')}</ConfirmButton>}
            {naming ? (
              <form className="row" onSubmit={save}>
                <input className="input sm" autoFocus value={name} maxLength={80} placeholder={t('views.name_placeholder')}
                  aria-label={t('views.name_label')} onChange={(e) => setName(e.target.value)} />
                <button type="submit" className="btn sm primary" disabled={!name.trim()}>{t('common.save')}</button>
                <button type="button" className="btn sm ghost" onClick={() => setNaming(false)}>{t('common.cancel')}</button>
              </form>
            ) : (
              <button type="button" className="btn sm" onClick={() => setNaming(true)}><Save size={15} /> {t('views.save')}</button>
            )}
          </div>
        )}
      </div>

      {view === null ? (
        <div className="card"><Spinner /></div>
      ) : widgets.length ? (
        <div className="widget-grid">
          {widgets.map((w, i) => (
            <Widget key={`${w.source}-${w.visual}-${JSON.stringify(w.params)}`} widget={w} onRemove={() => remove(i)} />
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
