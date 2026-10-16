// SPDX-License-Identifier: AGPL-3.0-or-later
import { Suspense, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { AlertTriangle, RotateCw } from 'lucide-react'
import { AppProvider } from '../context/AppContext'
import { useLanguage } from '../context/LanguageContext'
import { MetaProvider, useMeta } from '../context/MetaContext'
import Sidebar from './layout/Sidebar'
import Topbar from './layout/Topbar'
import { EmptyState, Spinner } from './ui'

function readCollapsed() {
  try {
    return localStorage.getItem('sidebar') === 'collapsed'
  } catch {
    return false
  }
}

function Shell() {
  const { t } = useLanguage()
  const { loading, error, reload } = useMeta()
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)

  function toggleCollapse() {
    setCollapsed((c) => {
      try {
        localStorage.setItem('sidebar', c ? 'open' : 'collapsed')
      } catch {
        /* préférence non persistée */
      }
      return !c
    })
  }

  return (
    <div className={`app ${collapsed ? 'collapsed' : ''}`}>
      <Sidebar open={open} collapsed={collapsed} onClose={() => setOpen(false)} onToggleCollapse={toggleCollapse} />
      <div className="app-main">
        <Topbar onMenu={() => setOpen(true)} />
        <main className="container">
          {loading ? <div className="page"><Spinner /></div> : null}
          {error ? (
            <div className="page">
              <EmptyState icon={AlertTriangle} title={t('nav.loading_error')}>
                <button type="button" className="btn sm" style={{ marginTop: 10 }} onClick={reload}><RotateCw size={14} /> {t('nav.retry')}</button>
              </EmptyState>
            </div>
          ) : null}
          {!loading && !error ? (
            <Suspense fallback={<div className="page"><Spinner /></div>}>
              <Outlet />
            </Suspense>
          ) : null}
        </main>
      </div>
    </div>
  )
}

// Espace connecté : profil, configuration et description des modules (/api/meta) partagés par toutes les pages
export default function AppLayout() {
  return (
    <AppProvider>
      <MetaProvider>
        <Shell />
      </MetaProvider>
    </AppProvider>
  )
}
