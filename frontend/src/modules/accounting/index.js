// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy } from 'react'

export default {
  components: {
    'accounting.vat': lazy(() => import('./Vat')),
    'accounting.urssaf': lazy(() => import('./Urssaf')),
    'accounting.documents': lazy(() => import('./Documents')),
  },
}
