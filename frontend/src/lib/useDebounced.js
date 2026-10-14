// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'

// Valeur qui suit `value` après `delay` ms sans changement (recherche, aperçu des calculs)
export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}
