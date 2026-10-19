// SPDX-License-Identifier: AGPL-3.0-or-later
// Point d'entrée de apercu.html : l'animation seule, avec ses contrôles (lecture, timeline, export MP4).
import { createRoot } from 'react-dom/client'
import CaffeinPromo from './CaffeinPromo.jsx'

createRoot(document.getElementById('root')).render(<CaffeinPromo />)
