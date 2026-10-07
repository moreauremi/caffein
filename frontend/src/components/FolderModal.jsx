// SPDX-License-Identifier: AGPL-3.0-or-later
import { ExternalLink, FileText, FolderOpen } from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'
import { date } from '../lib/format'
import { useApi } from '../lib/useApi'
import { EmptyState, Modal, Spinner } from './ui'

function size(bytes) {
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} Mo` : `${Math.max(1, Math.round(bytes / 1024))} Ko`
}

// Accès rapide aux dossiers du classement local (ex-dossiers Google Drive)
export default function FolderModal({ folderKey, onClose }) {
  const { t, language } = useLanguage()
  const { data, loading } = useApi(`/api/folders/${folderKey}`)
  return (
    <Modal title={data?.name || t('folders.title')} onClose={onClose} wide>
      {data && <div className="code" style={{ marginBottom: 14 }}>data/{data.path}</div>}
      {loading && <Spinner />}
      {data && !data.files.length && <EmptyState icon={FolderOpen} title={t('folders.empty')} />}
      {data && data.files.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>{t('folders.file')}</th><th className="hide-mobile">{t('folders.folder')}</th><th className="right">{t('folders.size')}</th><th className="right hide-mobile">{t('folders.modified')}</th><th /></tr></thead>
            <tbody>
              {data.files.map((f) => (
                <tr key={f.path}>
                  <td><span className="row" style={{ gap: 8 }}><FileText size={16} className="muted" /><span className="truncate" style={{ maxWidth: 280 }}>{f.name}</span></span></td>
                  <td className="muted small hide-mobile">{f.folder === '.' ? '—' : f.folder}</td>
                  <td className="right mono small">{size(f.size)}</td>
                  <td className="right small muted hide-mobile">{date(new Date(f.modified * 1000), language, 'medium')}</td>
                  <td className="right">
                    <a className="icon-btn" href={`/api/folders/${folderKey}/file?path=${encodeURIComponent(f.path)}`} target="_blank" rel="noreferrer" aria-label={t('common.open')}>
                      <ExternalLink size={16} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
