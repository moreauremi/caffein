// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy } from 'react'

export default {
  components: {
    'settings.account': lazy(() => import('./Account')),
    'settings.appearance': lazy(() => import('./Appearance')),
    'settings.company': lazy(() => import('./Company')),
    'settings.fiscal': lazy(() => import('./Fiscal')),
    'settings.notifications': lazy(() => import('./Notifications')),
    'settings.users': lazy(() => import('./Users')),
    'settings.roles': lazy(() => import('./Roles')),
    'settings.modules': lazy(() => import('./Modules')),
    'settings.automations': lazy(() => import('./Automations')),
    'settings.about': lazy(() => import('./About')),
  },
}
