// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react'
import { CheckCircle2, ScanLine, UploadCloud, XCircle } from 'lucide-react'
import { useLanguage } from '../../context/LanguageContext'
import { useToast } from '../../context/ToastContext'
import { api } from '../../lib/api'
import { money } from '../../lib/format'

const MIN_SCAN_MS = 2400 // animation de traitement (doc : 2,4 secondes)

// Glisser-déposer → « Factures à traiter » → script process_inbox (IA, chiffrement, rangement)
export default function DropZone({ onDone, compact = false }) {
  const { t, language } = useLanguage()
  const toast = useToast()
  const input = useRef(null)
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState([])

  async function upload(fileList) {
    const files = [...fileList]
    if (!files.length || busy) return
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    setBusy(true)
    setResults([])
    const started = Date.now()
    try {
      const { run } = await api.post('/api/documents/upload', form)
      await new Promise((r) => setTimeout(r, Math.max(0, MIN_SCAN_MS - (Date.now() - started))))
      const res = run.details?.results || []
      setResults(res)
      const ok = res.filter((r) => r.ok).length
      if (ok) toast(t('drop.done', { n: ok }))
      if (res.length - ok) toast(t('drop.set_aside', { n: res.length - ok }), 'error')
      onDone?.(run)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="stack">
      <div
        className={`dropzone ${over ? 'over' : ''} ${busy ? 'scan' : ''}`}
        style={compact ? { padding: '20px 14px' } : undefined}
        role="button" tabIndex={0} aria-busy={busy}
        onClick={() => !busy && input.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files) }}
      >
        <input ref={input} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp" hidden onChange={(e) => upload(e.target.files)} />
        <div className="dropzone-icon">{busy ? <ScanLine size={22} /> : <UploadCloud size={22} />}</div>
        <div style={{ fontWeight: 650 }}>{busy ? t('drop.scanning') : t('drop.title')}</div>
        <div className="small muted" style={{ marginTop: 4 }}>{busy ? t('drop.scanning_hint') : t('drop.hint')}</div>
      </div>
      {results.length > 0 && (
        <div className="list" aria-live="polite">
          {results.map((r, i) => (
            <div className="list-item" key={i} style={{ padding: '8px 0' }}>
              {r.ok ? <CheckCircle2 size={17} style={{ color: 'var(--good)' }} /> : <XCircle size={17} style={{ color: 'var(--bad)' }} />}
              <div className="grow">
                <div className="small truncate" style={{ fontWeight: 600 }}>{r.ok ? r.fournisseur : r.file}</div>
                <div className="xsmall muted truncate">
                  {r.ok ? `${money(r.ttc, language)} · ${r.categorie} · ${t(r.tva_type === 'collected' ? 'tva.collected_short' : 'tva.deductible_short')}` : r.reason}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
