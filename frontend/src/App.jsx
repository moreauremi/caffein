// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './components/ProtectedRoute'
import { EmptyState, Spinner } from './components/ui'
import { AuthProvider } from './context/AuthContext'
import { LanguageProvider, useLanguage } from './context/LanguageContext'
import { ThemeProvider } from './context/ThemeContext'
import { ToastProvider } from './context/ToastContext'
import ModulePage, { HomeIndex } from './pages/ModulePage'

// Pages chargées à la demande (bundle initial plus léger) ; les écrans des modules le sont aussi (src/modules)
const Login = lazy(() => import('./pages/Login'))
const PublicInvoice = lazy(() => import('./pages/PublicInvoice'))
const Setup = lazy(() => import('./pages/Setup'))

// Adresses d'avant les modules → pages des modules (les paramètres de l'adresse sont conservés)
const LEGACY = {
  factures: '/ventes/factures', tva: '/comptabilite/tva', urssaf: '/comptabilite/urssaf',
  documents: '/comptabilite/justificatifs', automatisations: '/parametres/automatisations', vues: '/accueil/vues',
}

function LegacyRedirect({ to }) {
  const { search } = useLocation()
  return <Navigate to={`${to}${search}`} replace />
}

function NotFound() {
  const { t } = useLanguage()
  return (
    <div className="container page">
      <EmptyState title={t('common.not_found')}><Link className="link" to="/">{t('common.back_home')}</Link></EmptyState>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <LanguageProvider>
          <ToastProvider>
            <AuthProvider>
              <Suspense fallback={<div className="container page"><Spinner /></div>}>
                <Routes>
                  <Route path="/login" element={<Login />} />
                  <Route path="/setup" element={<Setup />} />
                  <Route path="/f/:token" element={<PublicInvoice />} />
                  <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
                    <Route index element={<HomeIndex />} />
                    {Object.entries(LEGACY).map(([path, to]) => <Route key={path} path={path} element={<LegacyRedirect to={to} />} />)}
                    <Route path=":moduleSlug" element={<ModulePage />} />
                    <Route path=":moduleSlug/:pageSlug" element={<ModulePage />} />
                  </Route>
                  {/* anciennes adresses /app/… (v2.0 sans installation) */}
                  <Route path="/app/*" element={<Navigate to="/" replace />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </AuthProvider>
          </ToastProvider>
        </LanguageProvider>
      </ThemeProvider>
    </BrowserRouter>
  )
}
