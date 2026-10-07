// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMemo, useState } from 'react'
import {
  Bot, ExternalLink, FileStack, Folder, FolderInput, Lock, Pencil, ScanLine, Search, Trash2,
} from 'lucide-react'
import DropZone from '../components/DropZone'
import FolderModal from '../components/FolderModal'
import { EmptyState, Modal, Spinner, TvaType } from '../components/ui'
import { useLanguage } from '../context/LanguageContext'
import { useToast } from '../context/ToastContext'
import { api } from '../lib/api'
import { date, money } from '../lib/format'
import { useApi } from '../lib/useApi'

const CATEGORIES = ['Prestations', 'Frais fixes', 'Marketing', 'Logiciels/SaaS', 'Transport', 'Matériel', 'Autres']

function EditModal({ doc, onClose, onSaved }) {
  const { t } = useLanguage()
  const toast = useToast()
  const [form, setForm] = useState({ ...doc })
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function save() {
    setSaving(true)
    try {
      await api.put(`/api/documents/${doc.id}`, {
        fournisseur: form.fournisseur, date: form.date, categorie: form.categorie, resume: form.resume, tva_type: form.tva_type,
        ht: Number(form.ht), tva: Number(form.tva), ttc: Number(form.ttc),
      })
      toast(t('docs.saved'))
      onSaved()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={t('docs.edit')} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>{t('common.cancel')}</button><button className="btn primary" onClick={save} disabled={saving}>{saving && <Spinner />}{t('common.save')}</button></>}>
      <div className="form-grid">
        <div className="field full"><label>{t('docs.supplier')}</label><input className="input" value={form.fournisseur} onChange={set('fournisseur')} /></div>
        <div className="field"><label>{t('docs.date')}</label><input className="input" type="date" value={form.date || ''} onChange={set('date')} /></div>
        <div className="field">
          <label>{t('docs.type')}</label>
          <select className="select" value={form.tva_type} onChange={set('tva_type')}>
            <option value="deductible">{t('tva.deductible')}</option><option value="collected">{t('tva.collected')}</option>
          </select>
        </div>
        <div className="field"><label>HT</label><input className="input num mono" type="number" step="0.01" value={form.ht} onChange={set('ht')} /></div>
        <div className="field"><label>TVA</label><input className="input num mono" type="number" step="0.01" value={form.tva} onChange={set('tva')} /></div>
        <div className="field"><label>TTC</label><input className="input num mono" type="number" step="0.01" value={form.ttc} onChange={set('ttc')} /></div>
        <div className="field">
          <label>{t('docs.category')}</label>
          <select className="select" value={form.categorie} onChange={set('categorie')}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
        </div>
        <div className="field full"><label>{t('docs.summary')}</label><input className="input" value={form.resume} onChange={set('resume')} /></div>
      </div>
    </Modal>
  )
}

export default function Documents() {
  const { t, language } = useLanguage()
  const toast = useToast()
  const docs = useApi('/api/documents')
  const folders = useApi('/api/folders')
  const automations = useApi('/api/automations')
  const [type, setType] = useState('all')
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(null)
  const [folder, setFolder] = useState(null)
  const [scanning, setScanning] = useState(false)

  const reload = () => { docs.reload(); folders.reload(); automations.reload() }

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (docs.data || [])
      .filter((d) => type === 'all' || d.tva_type === type)
      .filter((d) => category === 'all' || d.categorie === category)
      .filter((d) => !q || [d.fournisseur, d.resume, d.categorie].some((v) => (v || '').toLowerCase().includes(q)))
  }, [docs.data, type, category, query])

  const totals = useMemo(() => list.reduce((acc, d) => ({ ht: acc.ht + d.ht, tva: acc.tva + d.tva, ttc: acc.ttc + d.ttc }), { ht: 0, tva: 0, ttc: 0 }), [list])

  async function scanNow() {
    setScanning(true)
    try {
      const run = await api.post('/api/automations/process_inbox/run')
      toast(run.summary, run.status === 'error' ? 'error' : 'success')
      reload()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setScanning(false)
    }
  }

  async function remove(d) {
    if (!window.confirm(t('docs.delete_confirm', { name: d.fournisseur }))) return
    try {
      await api.del(`/api/documents/${d.id}`)
      toast(t('docs.deleted'))
      reload()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const inbox = automations.data?.inbox_count ?? 0
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('docs.title')}</h1>
          <p className="page-sub row" style={{ gap: 6 }}><Lock size={14} /> {t('docs.subtitle')}</p>
        </div>
      </div>

      <div className="grid grid-main">
        <div className="card">
          <div className="card-head">
            <div className="card-title"><FolderInput size={16} /> {t('docs.drop_title')}</div>
            <span className="badge outline"><Bot /> {automations.data?.ai?.mode === 'claude' ? t('docs.ai_claude') : t('docs.ai_local')}</span>
          </div>
          <DropZone onDone={reload} />
        </div>
        <div className="card">
          <div className="card-head"><div className="card-title"><Folder size={16} /> {t('docs.folders')}</div></div>
          <div className="row between" style={{ padding: '4px 0 14px' }}>
            <div>
              <div className="small" style={{ fontWeight: 600 }}>{t('folders.a_traiter')}</div>
              <div className="xsmall muted">{t('docs.inbox_waiting', { n: inbox })}</div>
            </div>
            <button className="btn sm" onClick={scanNow} disabled={scanning}>{scanning ? <Spinner /> : <ScanLine size={15} />} {t('docs.scan_now')}</button>
          </div>
          <div className="list">
            {(folders.data || []).filter((f) => !['a_traiter', 'factures'].includes(f.key)).map((f) => (
              <button key={f.key} className="list-item" style={{ background: 'none', border: 0, borderBottom: '1px solid var(--border)', cursor: 'pointer', textAlign: 'left', padding: '10px 0' }} onClick={() => setFolder(f.key)}>
                <span className="list-icon"><Folder size={16} /></span>
                <span className="small grow" style={{ fontWeight: 550 }}>{t(`folders.${f.key}`)}</span>
                <span className="badge">{f.files}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card flush section-gap">
        <div className="row between wrap" style={{ padding: '14px 16px', gap: 12 }}>
          <div className="chips">
            {['all', 'deductible', 'collected'].map((k) => (
              <button key={k} className={`chip ${type === k ? 'active' : ''}`} onClick={() => setType(k)}>
                {k === 'all' ? t('invoices.filter_all') : t(`tva.${k}`)}
              </button>
            ))}
          </div>
          <div className="row wrap">
            <select className="select sm" style={{ width: 200 }} value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t('docs.category')}>
              <option value="all">{t('docs.all_categories')}</option>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
            <div className="input-icon" style={{ width: 220 }}>
              <Search size={16} />
              <input className="input sm" placeholder={t('common.search')} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t('common.search')} />
            </div>
          </div>
        </div>
        {docs.loading ? <div style={{ padding: 20 }}><div className="skeleton" style={{ height: 200 }} /></div> : list.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('docs.date')}</th><th>{t('docs.supplier')}</th><th className="hide-mobile">{t('docs.category')}</th>
                  <th className="right hide-mobile">HT</th><th className="right hide-mobile">TVA</th><th className="right">TTC</th>
                  <th>{t('docs.type')}</th><th className="hide-mobile">{t('docs.extraction')}</th><th />
                </tr>
              </thead>
              <tbody>
                {list.map((d) => (
                  <tr key={d.id}>
                    <td className="small nowrap">{date(d.date, language)}</td>
                    <td>
                      <div style={{ fontWeight: 600 }} className="truncate">{d.fournisseur}</div>
                      <div className="xsmall muted truncate" style={{ maxWidth: 280 }}>{d.resume}</div>
                    </td>
                    <td className="small hide-mobile">{d.categorie}</td>
                    <td className="right mono small hide-mobile">{money(d.ht, language)}</td>
                    <td className="right mono small hide-mobile">{money(d.tva, language)}</td>
                    <td className="right mono">{money(d.ttc, language)}</td>
                    <td><TvaType type={d.tva_type} /></td>
                    <td className="hide-mobile nowrap"><span className="xsmall muted">{t(`docs.by_${d.extracted_by || 'caffein'}`)}</span></td>
                    <td className="right">
                      <div className="actions">
                        {d.has_file && <a className="icon-btn" href={`/api/documents/${d.id}/file`} target="_blank" rel="noreferrer" aria-label={t('common.open')}><ExternalLink size={15} /></a>}
                        {d.source !== 'invoice' && <button className="icon-btn" aria-label={t('common.edit')} onClick={() => setEditing(d)}><Pencil size={15} /></button>}
                        {d.source !== 'invoice' && <button className="icon-btn" aria-label={t('common.delete')} onClick={() => remove(d)}><Trash2 size={15} /></button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="hide-mobile">
                  <td colSpan={3} className="small muted hide-mobile" style={{ padding: '12px 14px' }}>{t('docs.total', { n: list.length })}</td>
                  <td className="right mono small hide-mobile">{money(totals.ht, language)}</td>
                  <td className="right mono small hide-mobile">{money(totals.tva, language)}</td>
                  <td className="right mono small" style={{ fontWeight: 600 }}>{money(totals.ttc, language)}</td>
                  <td colSpan={3} />
                </tr>
              </tfoot>
            </table>
          </div>
        ) : <EmptyState icon={FileStack} title={t('docs.empty')}>{t('docs.empty_hint')}</EmptyState>}
      </div>

      {editing && <EditModal doc={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}
      {folder && <FolderModal folderKey={folder} onClose={() => setFolder(null)} />}
    </div>
  )
}
