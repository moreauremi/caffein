// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy } from 'react'

export default {
  components: {
    'home.dashboard': lazy(() => import('./Dashboard')),
    'home.views': lazy(() => import('./Views')),
  },
}
