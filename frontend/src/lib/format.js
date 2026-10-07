// SPDX-License-Identifier: AGPL-3.0-or-later
// Formats localisés (fr-FR / en-GB), montants en euros.
const localeOf = (lang) => (lang === 'en' ? 'en-GB' : 'fr-FR')

export function money(value, lang = 'fr', { decimals = 2, sign = false } = {}) {
  const v = Number(value || 0)
  const out = new Intl.NumberFormat(localeOf(lang), {
    style: 'currency', currency: 'EUR', minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(v)
  return sign && v > 0 ? `+${out}` : out
}

export function compactMoney(value, lang = 'fr') {
  const v = Number(value || 0)
  if (Math.abs(v) < 1000) return `${Math.round(v)} €`
  return new Intl.NumberFormat(localeOf(lang), { maximumFractionDigits: 1 }).format(v / 1000) + ' k€'
}

export function number(value, lang = 'fr', decimals = 0) {
  return new Intl.NumberFormat(localeOf(lang), { maximumFractionDigits: decimals }).format(Number(value || 0))
}

export function percent(ratio, lang = 'fr', decimals = 0) {
  return new Intl.NumberFormat(localeOf(lang), { style: 'percent', maximumFractionDigits: decimals }).format(ratio || 0)
}

function toDate(value) {
  if (!value) return null
  if (value instanceof Date) return value
  // 'AAAA-MM-JJ' → date locale (pas UTC) pour éviter les décalages d'un jour
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-').map(Number)
    return new Date(y, m - 1, d)
  }
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

export function date(value, lang = 'fr', style = 'short') {
  const d = toDate(value)
  if (!d) return '—'
  const opts = {
    short: { day: '2-digit', month: '2-digit', year: 'numeric' },
    medium: { day: 'numeric', month: 'short', year: 'numeric' },
    long: { day: 'numeric', month: 'long', year: 'numeric' },
    day: { weekday: 'long', day: 'numeric', month: 'long' },
    month: { month: 'long', year: 'numeric' },
    time: { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' },
  }[style]
  return new Intl.DateTimeFormat(localeOf(lang), opts).format(d)
}

export function relative(value, lang = 'fr') {
  const d = toDate(value)
  if (!d) return '—'
  const diff = (d.getTime() - Date.now()) / 1000
  const rtf = new Intl.RelativeTimeFormat(localeOf(lang), { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(Math.round(diff), 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day')
  return date(d, lang, 'medium')
}

export function daysFromNow(value, lang = 'fr') {
  const d = toDate(value)
  if (!d) return ''
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((d - today) / 86400000)
  return new Intl.RelativeTimeFormat(localeOf(lang), { numeric: 'auto' }).format(days, 'day')
}

export function duration(minutes, lang = 'fr') {
  const m = Math.round(minutes || 0)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const rest = m % 60
  if (lang === 'en') return rest ? `${h} h ${rest} min` : `${h} h`
  return rest ? `${h} h ${String(rest).padStart(2, '0')}` : `${h} h`
}

export function capitalize(text = '') {
  return text ? text[0].toLocaleUpperCase() + text.slice(1) : ''
}

export function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('') || 'C'
}

export function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
