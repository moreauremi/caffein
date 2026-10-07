// SPDX-License-Identifier: AGPL-3.0-or-later
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Spinner } from './ui'

// Garde de route : assistant d'installation tant qu'aucun compte n'existe, sinon connexion requise.
export default function ProtectedRoute({ children }) {
  const { loading, user, needsSetup } = useAuth()
  const location = useLocation()
  if (loading) return <div className="container page"><Spinner /></div>
  if (needsSetup) return <Navigate to="/setup" replace />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return children
}
