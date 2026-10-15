// SPDX-License-Identifier: AGPL-3.0-or-later
import { duration, money, number } from './format'

// Chiffre clé d'un module, déjà calculé par le serveur : on ne fait que le mettre en forme
export function kpiValue(kpi, language) {
  if (kpi.value === null || kpi.value === undefined) return '—'
  if (kpi.unit === 'money') return money(kpi.value, language)
  if (kpi.unit === 'minutes') return duration(kpi.value, language)
  if (kpi.unit === 'percent') return `${number(kpi.value, language, 1)} %`
  if (kpi.unit === 'days') return `${number(kpi.value, language, 1)} j`
  return number(kpi.value, language, 2)
}
