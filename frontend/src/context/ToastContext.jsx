// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useCallback, useContext, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'

const ToastContext = createContext(() => {})
const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info }

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const dismiss = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), [])

  const toast = useCallback((message, type = 'success') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((list) => [...list.slice(-3), { id, message, type }])
    setTimeout(() => dismiss(id), type === 'error' ? 7000 : 4200)
  }, [dismiss])

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICONS[t.type] || Info
          return (
            <div key={t.id} className={`toast ${t.type}`}>
              <Icon size={18} />
              <span>{t.message}</span>
              <button onClick={() => dismiss(t.id)} aria-label="Fermer"><X size={16} /></button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
