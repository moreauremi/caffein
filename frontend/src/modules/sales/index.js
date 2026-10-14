// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy } from 'react'

export default {
  components: {
    'sales.invoices': lazy(() => import('./Invoices')),
  },
}
