// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './components/ProtectedRoute'
import { EmptyState, Spinner } from './components/ui'
import { AuthProvider } from './context/AuthContext'
import { LanguageProvider, useLanguage } from './context/LanguageContext'
import { ThemeProvider } from './context/ThemeContext'
import { ToastProvider } from './context/ToastContext'

// Pages chargées à la demande (bundle initial plus léger)
const Automations = lazy(() => import('./pages/Automations'))
const CaffeinDashboard = lazy(() => import('./pages/CaffeinDashboard'))
const Documents = lazy(() => import('./pages/Documents'))
const Home = lazy(() => import('./pages/Home'))
const Invoices = lazy(() => import('./pages/Invoices'))
const Login = lazy(() => import('./pages/Login'))
const PublicInvoice = lazy(() => import('./pages/PublicInvoice'))
const Setup = lazy(() => import('./pages/Setup'))
const Urssaf = lazy(() => import('./pages/Urssaf'))

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
                    <Route index element={<Home />} />
                    <Route path="tva" element={<CaffeinDashboard />} />
                    <Route path="factures" element={<Invoices />} />
                    <Route path="documents" element={<Documents />} />
                    <Route path="urssaf" element={<Urssaf />} />
                    <Route path="automatisations" element={<Automations />} />
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
