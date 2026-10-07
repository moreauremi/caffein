// SPDX-License-Identifier: AGPL-3.0-or-later
// Applique le thème mémorisé avant le premier rendu (évite le flash blanc).
try {
  var theme = localStorage.getItem('theme')
  if (!theme) theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'sombre' : 'clair'
  document.documentElement.setAttribute('data-theme', theme)
} catch { /* stockage indisponible */ }
