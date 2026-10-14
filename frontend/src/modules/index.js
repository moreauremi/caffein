// SPDX-License-Identifier: AGPL-3.0-or-later
// Écrans sur mesure des modules. Le serveur désigne l'écran d'une page par « module.écran » (Page.component) ;
// une page d'entité (Page.entity) est générée sans rien ajouter ici. Voir docs/modules.md.
//
// Ajouter un module avec des écrans sur mesure : créer src/modules/<clé>/index.js qui exporte
// { components: { '<clé>.<écran>': lazy(() => import('./Ecran')) }, translations: { 'clé': ['fr', 'en'] } },
// puis l'ajouter à la liste ci-dessous.
import { registerTranslations } from '../lib/i18n'
import accounting from './accounting'
import home from './home'
import sales from './sales'
import settings from './settings'

const FRONTEND_MODULES = [home, sales, accounting, settings]

export const COMPONENTS = Object.assign({}, ...FRONTEND_MODULES.map((m) => m.components || {}))

for (const module of FRONTEND_MODULES) registerTranslations(module.translations)
