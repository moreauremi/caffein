// SPDX-License-Identifier: AGPL-3.0-or-later
// Dernière vue affichée dans « Mes vues », gardée dans le navigateur pour la retrouver en revenant.
// Une clé par utilisateur, effacée à la déconnexion (navigateur partagé). Le stockage peut être
// indisponible (navigation privée…) : la vue n'est alors simplement pas gardée.
const PREFIX = 'caffein.views.'

export function readCurrentView(userId) {
  if (!userId) return null
  try {
    return JSON.parse(localStorage.getItem(`${PREFIX}${userId}`) || 'null')
  } catch {
    return null
  }
}

export function storeCurrentView(userId, value) {
  if (!userId) return
  try {
    localStorage.setItem(`${PREFIX}${userId}`, JSON.stringify(value))
  } catch {
    /* stockage indisponible */
  }
}

export function clearStoredViews() {
  try {
    Object.keys(localStorage).filter((key) => key.startsWith(PREFIX)).forEach((key) => localStorage.removeItem(key))
  } catch {
    /* stockage indisponible */
  }
}
