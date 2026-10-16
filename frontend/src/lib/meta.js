// SPDX-License-Identifier: AGPL-3.0-or-later
// Outils autour de la description de l'espace (/api/meta).
export const LEVELS = { none: 0, read: 1, write: 2, manage: 3 }
export const LEVEL_NAMES = ['none', 'read', 'write', 'manage']

export function pagePath(module, page) {
  return page.path || `/${module.slug}/${page.slug}`
}

// Module affiché pour une adresse : « / » est l'Accueil, sinon le premier segment est l'adresse du module.
export function moduleForPath(modules, pathname) {
  if (pathname === '/' || pathname === '') return modules.find((m) => m.key === 'home') || null
  const slug = pathname.split('/')[1]
  return modules.find((m) => m.slug === slug) || null
}

// Valeur numérique saisie (« 1 250,50 ») → nombre, ou la saisie telle quelle si elle n'en est pas un
export function parseNumber(value) {
  if (typeof value === 'number') return value
  const text = String(value ?? '').replace(/\s/g, '').replace(',', '.')
  if (text === '') return null
  const n = Number(text)
  return Number.isFinite(n) ? n : value
}
