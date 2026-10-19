// SPDX-License-Identifier: AGPL-3.0-or-later
// CaffeinPromo.jsx : animation de présentation de Caffein (35 s, 16:9).
//
// Composant React autonome : aucune dépendance hors React, polices chargées depuis Google Fonts.
// Toute l'animation est calculée à partir d'un seul temps `t` (en secondes) : on peut la mettre
// en pause, la rejouer, se déplacer dans la timeline, ou la piloter de l'extérieur avec `time`
// (pratique pour exporter une vidéo image par image).
//
//   <CaffeinPromo />                                   lecture auto, contrôles affichés
//   <CaffeinPromo loop showControls={false} />          boucle, sans contrôles (borne, salon)
//   <CaffeinPromo time={12.5} showControls={false} />   image figée à 12,5 s
//
// Bouton « MP4 » : rend l'animation image par image en 1920 × 1080 (30 i/s) dans le navigateur, l'encode
// en H.264 avec WebCodecs et télécharge caffein-presentation.mp4. Rien n'est envoyé sur un serveur.
// Chrome ou Edge récents (H.264). Sans H.264 (Chromium sous Linux…), la vidéo est encodée en VP9 dans
// le même conteneur MP4 : elle se lit dans Chrome, Firefox et VLC, pas dans QuickTime.
//
// Timeline
//   0 – 4 s    Intro : un point tombe, s'étire, le logo en jaillit ; plongée dans le point du « i »
//   4 – 9 s    Les trucs chiants tombent et s'empilent… puis sont aspirés par le noyau de l'IA
//   9 – 15 s   Le noyau devient la barre de saisie : un devis en une phrase
//   15 – 21 s  Le devis se replie en panneau : justificatifs, relances, Mes vues
//   21 – 26 s  Les panneaux fusionnent en interrupteur : on coupe l'IA, tout marche pareil
//   26 – 31 s  Panoramique éclair : 100 % libre, git clone, 13 modules
//   31 – 35 s  La pastille AGPL envahit l'écran : outro
//
// Pas de rideau entre les scènes : ce sont les éléments qui se transforment d'une scène à l'autre, avec des
// accélérations exponentielles, des ralentis et du flou de vitesse.

import { useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

export const DURATION = 35
const W = 1280
const H = 720

const C = {
  bg: '#FAFAF8',
  fg: '#1A1A18',
  surface: '#FFFFFF',
  surface2: '#F4F4F1',
  surface3: '#ECECE8',
  border: '#E8E8E4',
  borderStrong: '#D6D6D0',
  accent: '#E8510E',
  accentInk: '#B83E07',
  accentSoft: 'rgba(232, 81, 14, 0.10)',
  muted: '#6B6B66',
  subtle: '#96968F',
  good: '#15803d',
  goodSoft: 'rgba(21, 128, 61, 0.10)',
  bad: '#dc2626',
  badSoft: 'rgba(220, 38, 38, 0.09)',
  dark: '#161614',
  darkFg: '#F5F5F2',
}
const SANS = "'DM Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"
const SERIF = "'Instrument Serif', Georgia, serif"
const MONO = "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"
const SHADOW = '0 1px 2px rgba(20,20,18,.05), 0 18px 40px -18px rgba(20,20,18,.28)'

/* ─── Outils de timing ─────────────────────────────────────────────── */
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const prog = (t, start, dur) => clamp((t - start) / dur)
const lerp = (a, b, k) => a + (b - a) * k
const eOut = (x) => 1 - Math.pow(1 - x, 3)
const eInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)
const eBack = (x) => {
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2)
}
const eBounce = (x) => {
  const n = 7.5625
  const d = 2.75
  if (x < 1 / d) return n * x * x
  if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75
  if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375
  return n * (x -= 2.625 / d) * x + 0.984375
}
const eInExpo = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, 10 * x - 10))
const eOutExpo = (x) => (x >= 1 ? 1 : x <= 0 ? 0 : 1 - Math.pow(2, -10 * x))
const eInOutExpo = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2)
const lerpRect = (a, b, k) => a.map((v, i) => lerp(v, b[i], k))
const typed = (str, t, start, cps = 28) => str.slice(0, Math.max(0, Math.floor((t - start) * cps)))
const typingDone = (str, t, start, cps = 28) => t >= start + str.length / cps

// Apparition douce (fondu + glissé vers le haut)
const appear = (t, start, dur = 0.55, dy = 26) => {
  const p = eOut(prog(t, start, dur))
  return { opacity: p, transform: `translateY(${(1 - p) * dy}px)` }
}
// Apparition « pop » (échelle avec rebond)
const pop = (t, start, dur = 0.5, extra = '') => {
  const p = prog(t, start, dur)
  return { opacity: clamp(p * 3), transform: `${extra} scale(${eBack(p)})` }
}
// Sortie : accélère (exponentielle) avec flou de vitesse. Entrée : arrive vite puis ralentit longuement.
const leave = (t, start, dur = 0.45, { x = 0, y = 0, s = 1, r = 0, blur = 10 } = {}) => {
  const k = eInExpo(prog(t, start, dur))
  if (k <= 0) return {}
  return { opacity: 1 - eInExpo(prog(t, start + dur * 0.4, dur * 0.6)),
    transform: `translate(${x * k}px, ${y * k}px) scale(${lerp(1, s, k)}) rotate(${r * k}deg)`, filter: `blur(${k * blur}px)` }
}
const enter = (t, start, dur = 0.6, { x = 0, y = 0, s = 1, r = 0, blur = 10 } = {}) => {
  const k = eOutExpo(prog(t, start, dur))
  if (k >= 1) return {}
  return { opacity: clamp(prog(t, start, dur * 0.3)),
    transform: `translate(${x * (1 - k)}px, ${y * (1 - k)}px) scale(${lerp(s, 1, k)}) rotate(${r * (1 - k)}deg)`, filter: `blur(${(1 - k) * blur}px)` }
}
// Coup de caméra : zoom bref et sec, puis retour souple
const punch = (t, at, amp = 0.035) => amp * eOutExpo(prog(t, at, 0.12)) * (1 - eInOut(prog(t, at + 0.12, 0.6)))
const euro = (v) =>
  v.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'
const abs = (x, y, extra = {}) => ({ position: 'absolute', left: x, top: y, ...extra })

/* ─── Icônes (traits 24×24, style lucide) ──────────────────────────── */
const ICONS = {
  mail: 'M4 5h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z M2 7l10 6 10-6',
  folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  percent: 'M19 5L5 19 M4 6.5a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M15 17.5a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0',
  doc: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M9 13h6 M9 17h4',
  bank: 'M3 21h18 M5 21V11 M19 21V11 M9.5 21V11 M14.5 21V11 M12 3L3 8h18z',
  box: 'M21 8l-9-5-9 5 9 5 9-5z M3 8v8l9 5 9-5V8 M12 13v8',
  sparkle: 'M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z',
  check: 'M20 6L9 17l-5-5',
  lock: 'M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z M8 11V7a4 4 0 0 1 8 0v4',
  chart: 'M3 3v18h18 M8 17v-5 M13 17V8 M18 17v-8',
  server: 'M4 4h16v6H4z M4 14h16v6H4z M8 7h.01 M8 17h.01',
  github:
    'M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  clock: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z M12 7v5l3 2',
  scale: 'M12 3v18 M5 21h14 M3 8l3-4 3 4a3 3 0 0 1-6 0z M15 8l3-4 3 4a3 3 0 0 1-6 0z M6 4h12',
}
function Icon({ name, size = 20, color = 'currentColor', stroke = 2 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke}
      strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block', flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  )
}

/* ─── Logo Caffein ─────────────────────────────────────────────────── */
// Logo officiel Caffein (mot-symbole, docs/logo/caffein-noir.svg), une forme par lettre pour les animer.
const LOGO_W = 1600.3
const LOGO_H = 288.0
const LOGO_LETTERS = [
  ['M83 80.3L80.3 81.3L77 81.7L74.3 82.7L71.7 83.0L61 86.7L59.3 87.7L58.3 87.7L54.7 89.3L54 90.0L52.7 90.3L52 91.0L44.3 95.0L36 101.0L33.3 103.7L31 105.3L25 111.3L17.7 120.7L14.3 126.0L11.3 131.7L11.3 132.3L10 134.3L5.3 146.0L2 159.0L1.7 163.0L0.7 167.3L0.7 170.0L0.3 170.3L0 179.3L0.3 179.7L0.3 193.0L0.7 193.3L0.7 197.0L1 197.3L1 199.3L1.7 202.0L1.7 204.7L2 205.0L2 206.3L2.7 208.0L2.7 209.7L4 214.0L4.3 216.7L5 217.7L5.3 220.0L6.3 222.0L7.7 226.7L11.7 235.7L16.7 244.3L23.7 253.7L31 261.3L38.3 267.3L43.7 271.0L44.7 271.3L45.7 272.3L52 276.0L55.7 277.3L57 278.3L59 278.7L60.7 279.7L66 281.3L67 282.0L69.3 282.3L71.3 283.3L73 283.3L75.7 284.3L79 284.7L81.7 285.7L86.7 286.0L87 286.3L92 286.7L92.3 287.0L96.3 287.0L96.7 287.3L99.3 287.3L99.7 287.7L117 287.3L117.3 287.0L124.3 286.7L126 286.0L129.3 285.7L132.3 284.7L135 284.3L137.3 283.3L139.7 283.0L140.7 282.3L143 282.0L144 281.3L150.3 279.3L151 278.7L151.7 278.7L157.7 275.7L165.3 271.0L176.3 262.3L179 259.7L188.7 248.3L195.7 236.7L196.3 234.7L197 234.0L197.3 232.3L198.3 231.0L198.7 229.3L199.7 228.0L201 224.0L201 223.0L202 221.3L202.3 219.3L203.3 217.0L203.3 215.7L204.7 212.0L204.7 211.0L204.3 210.7L162.3 210.7L161.3 212.0L161 214.0L157.3 221.3L157.3 222.0L154 227.3L150 232.7L143.3 239.3L138.3 243.3L126.3 249.3L124 249.7L121.7 250.7L120.3 250.7L116 252.0L105 252.3L104.7 252.0L98.7 252.0L98.3 251.7L94.7 251.3L84.7 248.3L81.3 247.0L77.3 244.7L76.7 244.7L71.7 241.7L62.3 233.3L57.3 227.0L54 221.7L49 210.7L48.7 208.3L47.7 206.3L46.3 201.0L46.3 199.0L45.3 195.0L44.7 181.7L45 181.3L45 173.3L45.3 173.0L45.3 170.3L46.3 166.7L46.3 165.0L47.7 161.0L47.7 159.7L48.3 158.7L48.7 156.7L51 151.3L51.3 149.7L52 149.0L56 141.3L62.3 133.0L68 127.7L75 122.7L82.3 119.0L83.3 119.0L85.3 118.0L89.3 116.7L91.7 116.3L94 115.3L97.3 115.3L99.7 114.7L103.7 114.7L104 114.3L108.7 114.3L109 114.7L119 115.3L123.7 116.7L133.7 120.7L142.7 126.7L150 134.0L155 140.7L158.7 147.3L158.7 148.0L160.7 152.0L161.3 154.7L162.3 155.7L166.7 155.7L167 156.0L204 156.0L204.7 155.0L203.3 151.3L203.3 150.0L202.3 147.7L202 145.3L201 143.7L201 142.7L199.7 138.7L198.7 137.3L198.7 136.7L194.7 128.3L188.3 118.0L183.7 112.0L177 105.0L171.3 100.0L164.7 95.0L157.3 90.7L155.3 90.0L154.7 89.3L153.3 89.0L149 86.7L143.7 85.0L142 84.0L139.7 83.7L138.7 83.0L137.3 83.0L134 81.7L130.7 81.3L127.7 80.3L125.7 80.3L125.3 80.0L119 79.3L118.7 79.0L115.3 79.0L115 78.7L98.7 78.7L98.3 79.0L91.3 79.3L91 79.7L86.3 80.0L86 80.3Z', 102.5],
  ['M324.3 102.7L318 109.3L313.7 115.0L313 116.7L311 119.3L311 120.0L308.3 125.3L308.3 126.3L307.3 128.0L307 130.3L306 133.0L306 135.3L305 139.3L305 144.3L305.3 144.7L349 144.7L349.7 143.7L349.7 140.0L351 135.7L353.7 131.0L358.7 126.0L361.3 124.0L368 120.3L370 120.0L371 119.3L376.7 117.7L378.3 117.7L381.7 116.7L389.3 116.0L389.7 115.7L404.3 115.7L407 116.3L412.7 116.7L422 119.0L430 122.7L433.3 125.0L439.7 131.7L442.3 136.3L442.3 137.3L443.3 139.0L443.7 141.0L444.7 143.3L445.3 150.7L445.7 151.0L445.7 166.0L445 166.7L389.7 166.7L389.3 167.0L377.7 167.0L377.3 167.3L371.3 167.3L371 167.7L368.3 167.7L368 168.0L364 168.0L363.7 168.3L361.7 168.3L361.3 168.7L357.3 169.0L357 169.3L354.3 169.3L351.3 170.3L344 171.7L341.7 172.7L339.3 173.0L335.3 174.3L333.7 175.3L332.7 175.3L325 179.0L324.3 179.0L315.7 184.7L308.3 191.3L304 197.3L302.3 200.3L302 201.7L301.3 202.3L301 204.0L300 205.7L300 206.7L298.7 209.7L298.7 211.3L297.7 214.3L297.3 223.0L297 223.3L297.7 236.0L300 246.0L300.7 247.0L301.3 249.7L302 250.3L302.3 252.0L304.7 256.3L309 262.7L312.3 266.3L319 272.3L321.3 273.7L323.7 275.7L334.7 281.0L336.3 281.3L337.3 282.0L339.7 282.3L341.7 283.3L344 283.7L346.7 284.7L348.3 284.7L351 285.7L355.3 286.0L359.3 287.0L365.7 287.3L366 287.7L387.3 287.7L390 287.0L396 286.7L397.7 286.0L399.3 286.0L404.3 284.7L406 284.7L409.7 283.3L411 283.3L414.3 282.0L415.3 282.0L417 281.0L421 279.7L428.3 275.7L434.7 271.0L441 264.7L443.7 261.0L445.3 259.3L446.3 259.3L447 261.3L447.3 267.3L448.3 270.3L448.7 274.0L449.7 276.3L449.7 278.0L450.7 280.3L451 282.7L452 283.3L494.3 283.3L495 283.0L495 279.3L493.3 275.0L492.7 272.0L492 271.0L491.7 268.0L491 266.7L490.7 261.7L490 259.0L490 256.0L489.7 255.7L489.7 247.0L489.3 246.7L489.3 156.7L489 156.3L489 151.7L488.7 151.3L488.7 149.0L488.3 148.7L488 142.7L487.7 142.3L487 137.3L486 134.3L485.7 131.7L483.3 124.7L481 120.0L481 119.3L480 118.0L479.7 116.7L477.3 113.3L476 110.7L472.3 106.0L466 99.7L459.7 94.7L452.3 90.3L447.7 88.7L446 87.7L445 87.7L444 87.0L441 86.3L436 84.3L433.3 84.0L429 82.7L423.3 82.0L423 81.7L416.7 81.3L416.3 81.0L410.3 80.7L410 80.3L399.3 80.3L399 80.0L384.3 80.3L384 80.7L375 81.3L374.7 81.7L370.7 82.0L369 82.7L364.7 83.0L363.3 83.7L360 84.0L356.3 85.3L355.3 85.3L353.3 86.3L352.3 86.3L350.3 87.3L348.7 87.7L346.3 89.0L343.3 90.0L338.7 92.7L338 92.7L333.7 95.3ZM445.7 196.7L445.7 202.7L445.3 203.0L445.3 205.3L445 205.7L444.7 211.3L444 213.0L443.3 217.7L442.3 220.0L442.3 221.7L441.3 223.3L439.7 228.3L435 236.3L431.3 240.7L426.3 245.3L417.3 251.0L414 252.0L412.3 253.0L410 253.3L407.7 254.3L404.7 254.7L401.3 255.7L396.7 256.0L394.7 256.7L389 256.7L388.7 257.0L377 256.7L375 256.0L371 255.7L368.3 254.7L365.3 254.3L364.3 253.7L361.3 253.0L354.3 249.7L351 247.3L346.7 243.0L343.7 238.3L343 235.7L342.3 234.7L342 230.7L341.7 230.3L341.7 222.7L342 222.3L342.3 218.7L343 217.7L343.7 215.0L344.3 214.3L345.7 211.3L350.7 206.0L353.7 203.7L360 200.3L361 200.3L362 199.7L364 199.3L366.3 198.3L369.3 198.0L372 197.0L374 197.0L376 196.3L382.7 196.0L383 195.7L390.3 195.7L390.7 195.3L403 195.3L403.3 195.7L444.7 195.7Z', 396.2],
  ['M655.3 14.7L654 15.7L653.3 15.7L650 17.3L645.3 20.7L644.3 21.0L637 28.3L633.7 32.7L631 37.0L631 37.7L628 43.7L627.3 46.7L626.3 48.3L626 51.0L625.3 52.3L625 55.0L624 58.0L623.7 62.7L623.3 63.0L623 67.0L622.7 67.3L622.3 82.0L621.3 83.0L589 83.0L588.3 84.3L588.3 114.7L588.7 115.3L589.3 115.7L621.3 115.7L622.3 116.7L622.3 283.0L623 283.3L665.7 283.3L666 283.0L666 116.7L666.7 115.7L707.7 115.7L708 116.0L708.7 115.7L739.7 115.7L740.3 116.7L740.3 282.7L741 283.3L783.7 283.3L784 283.0L784 117.0L785 115.7L832.7 115.7L833.7 115.0L833.7 83.7L833 83.0L785 83.0L784 82.0L784 74.0L784.3 73.7L784.3 70.0L784.7 69.7L785.3 64.0L786.3 61.7L786.7 59.3L788 57.0L788 56.3L791 51.7L796.7 47.0L801.3 45.0L804 44.7L805.7 44.0L808 44.0L808.3 43.7L822.7 43.3L823 43.7L827.3 43.7L827.7 44.0L830 44.0L832 44.7L835.3 44.7L835.7 45.0L838 45.0L839.7 45.7L841 45.7L841.7 44.7L841.7 11.7L840.3 10.7L838.3 10.7L834.7 9.7L829.7 9.3L829.3 9.0L825 8.7L824.7 8.3L818.3 8.3L818 8.0L801.3 8.3L801 8.7L795.3 9.0L793.3 9.7L790.3 9.7L790 10.0L788.3 10.0L784.3 11.0L782 12.0L779 12.7L778 13.3L777 13.3L775.3 14.3L773.3 14.7L772 15.7L770.7 16.0L770 16.7L766.3 18.3L761.7 21.7L754 29.7L750.7 34.3L749 37.3L749 38.0L748 39.3L747.7 40.7L747 41.3L745.3 46.0L745.3 47.0L744.3 48.7L744.3 50.0L743.3 52.7L743 55.3L742 58.7L742 61.0L741.7 61.3L741.7 63.3L741 65.3L741 68.3L740.7 68.7L740.3 82.0L739.3 83.0L666.7 83.0L666 82.3L666 72.3L666.3 72.0L666.3 69.3L667.3 65.3L667.3 63.7L668.3 61.3L668.7 59.0L669.3 58.3L669.7 57.0L672.3 52.3L675.3 49.3L678 47.3L680.3 46.0L684.3 44.7L686 44.7L687.3 44.0L696.3 43.7L696.7 43.3L709.3 43.7L709.7 44.0L711.7 44.0L714 44.7L720 45.0L721.3 45.7L723 45.7L723.3 45.3L723.3 11.3L722.3 10.7L720 10.7L716.7 9.7L711.3 9.3L711 9.0L707 8.7L706.7 8.3L689.3 8.0L689 8.3L679.3 8.7L675.3 9.7L670 10.0L664 12.0L661.7 12.3L660 13.3L659 13.3L657 14.3Z', 715.2],
  ['M1004.3 81.7L1002 82.7L1000.7 82.7L998.3 83.7L996 84.0L994.3 85.0L991.7 85.7L990 86.7L987 87.7L985.7 88.7L985 88.7L981 90.7L980.3 91.3L979.7 91.3L973.3 95.0L964.3 102.0L956 110.0L949 118.7L943.3 127.7L940.3 133.7L940.3 134.3L939.3 135.7L939 137.3L938 139.0L936.3 144.3L935.7 145.3L935.3 147.7L934.3 149.7L934.3 151.0L933 155.0L933 156.7L931.7 161.7L931.7 164.0L931.3 164.3L931 168.3L930.7 168.7L930.7 173.0L930.3 173.3L930.7 195.3L931 195.7L932 205.3L933 208.7L933 210.7L934 213.3L934.3 216.0L935.3 218.3L935.7 220.7L936.3 221.7L938 227.0L939 228.7L939 229.7L943 238.0L947.7 245.7L954.7 255.0L964.7 264.7L968 267.3L973.3 271.0L974.3 271.3L975.3 272.3L984.7 277.3L995 281.0L996 281.7L999.3 282.3L1001.3 283.3L1004 283.7L1006.3 284.7L1008.3 284.7L1012 285.7L1016.3 286.0L1018.7 286.7L1025.3 287.0L1025.7 287.3L1028.3 287.3L1028.7 287.7L1045.3 287.7L1045.7 287.3L1048 287.3L1048.3 287.0L1052 287.0L1056 286.0L1060.3 285.7L1063.3 284.7L1067 284.3L1073.3 282.0L1074.3 282.0L1075.3 281.3L1078 280.7L1079.7 279.7L1083.7 278.3L1085 277.3L1086.7 277.0L1087.3 276.3L1088 276.3L1092.3 273.7L1095.3 272.3L1102.3 267.3L1109 261.7L1117 253.3L1122 246.7L1127.3 238.0L1130 232.7L1130 232.0L1131 230.7L1131.3 229.0L1132.3 227.7L1132.3 226.7L1132 226.3L1083.7 226.3L1082.7 227.0L1080.7 229.7L1080.3 230.7L1075.7 236.0L1068.7 242.3L1064 245.3L1057.7 248.3L1056 248.7L1055 249.3L1052.7 249.7L1050.7 250.7L1046.7 251.0L1045 251.7L1042 251.7L1041.7 252.0L1031.7 252.0L1031.3 251.7L1027.7 251.7L1025 251.0L1022.7 251.0L1018.3 249.7L1017 249.7L1007.7 246.0L999.7 241.0L996.3 238.3L991 233.0L986.7 227.3L984 223.0L984 222.3L980.3 215.0L980 213.3L979 211.3L979 210.0L978 208.0L977.7 205.0L976.7 202.3L976.7 200.0L976.3 199.7L976 196.7L976.7 195.7L977.7 195.3L1135.7 195.3L1136.3 194.7L1136 173.3L1135.7 173.0L1135.7 170.3L1135 167.7L1134.7 162.3L1133.7 159.0L1133.7 157.0L1132.3 153.0L1132.3 151.7L1131.3 149.3L1131 146.7L1130 145.0L1129.7 143.0L1126.3 134.7L1125 132.3L1125 131.7L1120 123.0L1114 114.7L1109.7 109.7L1100.7 101.0L1091 94.0L1084.7 90.3L1080.3 88.7L1079.7 88.0L1074.3 85.7L1071.7 85.0L1069.7 84.0L1067.7 83.7L1066.7 83.0L1064 82.7L1062.3 81.7L1058.7 81.3L1055 80.3L1052.7 80.3L1048.7 79.3L1042 79.0L1041.7 78.7L1025.3 78.7L1025 79.0L1021.7 79.0L1021.3 79.3L1018.3 79.3L1015.7 80.0L1010.7 80.3L1007.7 81.3ZM976.3 165.3L976.7 165.0L976.7 163.0L977.7 160.0L978 157.3L979 155.3L979 154.0L980 152.3L980 151.3L981.3 148.0L984.3 142.0L990 133.7L997.3 126.3L1006.3 120.3L1009.3 119.0L1010.3 119.0L1012 118.0L1014.7 117.3L1015.7 116.7L1018.3 116.3L1021 115.3L1024 115.3L1024.3 115.0L1026.7 115.0L1027 114.7L1031 114.7L1031.3 114.3L1036 114.3L1036.3 114.7L1040 114.7L1040.3 115.0L1042.7 115.0L1043 115.3L1046 115.3L1055.3 118.0L1061 120.7L1061.7 121.3L1062.3 121.3L1071 127.7L1075.3 132.0L1078 135.3L1084 145.0L1085.3 149.0L1086.3 150.3L1087 153.3L1087.7 154.3L1088 156.7L1088.7 158.0L1090 163.3L1090.3 166.0L1089.7 166.7L977 166.7L976.3 166.0Z', 1033.5],
  ['M1253.7 1.3L1248 3.7L1242.7 7.7L1239 12.0L1237.3 15.0L1235.3 20.7L1235 24.7L1234.7 25.0L1235 33.3L1236.3 38.3L1237.3 40.0L1237.7 41.7L1241.3 47.0L1244 49.7L1249.3 53.0L1251.3 53.3L1253 54.3L1255.3 54.7L1256.3 55.3L1262.7 55.7L1263 56.0L1268.7 55.7L1269 55.3L1270.7 55.3L1274.7 54.3L1279 52.0L1280.3 51.7L1284.7 48.3L1287.7 45.0L1290.7 39.7L1292 36.0L1292 34.3L1293 30.7L1293 26.3L1292 22.3L1292 20.3L1290.7 17.0L1290.7 16.0L1287.7 10.7L1283 6.0L1277.7 2.7L1276 2.3L1274.3 1.3L1271.3 1.0L1268.3 0.0L1259.3 0.0L1256.3 1.0ZM1243.7 83.0L1242.7 83.7L1242.7 283.0L1243 283.3L1285.7 283.3L1286.3 282.7L1286.3 84.0L1285.3 83.0Z', 1264.0],
  ['M1576.7 100.0L1569.3 94.0L1561.3 89.0L1560.7 89.0L1553.3 85.7L1551.3 85.3L1544.7 83.0L1541 82.7L1538.3 81.7L1533.7 81.3L1533.3 81.0L1529.3 80.7L1529 80.3L1519.7 80.3L1519.3 80.0L1508.7 80.3L1508.3 80.7L1506 80.7L1503.3 81.3L1497.3 81.7L1494.7 82.7L1492 83.0L1489.7 84.0L1488.3 84.0L1487.3 84.7L1481.7 86.3L1479.3 87.7L1475.7 89.0L1474.3 90.0L1473 90.3L1467.3 93.7L1460.7 98.7L1454.3 105.0L1450.7 109.7L1449.3 112.0L1448.3 113.0L1447.7 113.0L1447 111.7L1447 107.7L1446.7 107.3L1446.7 100.7L1446.3 100.3L1446.3 94.0L1446 93.7L1445.7 84.7L1444.7 83.0L1407.3 83.0L1406.7 83.7L1406.7 283.0L1407 283.3L1450 283.3L1450.3 283.0L1450.3 161.0L1451.3 157.0L1451.3 155.0L1452.3 152.3L1452.7 150.0L1455.3 143.3L1460.7 135.0L1464.3 131.0L1471.3 125.3L1475.7 122.7L1476.3 122.7L1480.3 120.3L1483 119.7L1484 119.0L1493.3 116.7L1502.3 116.0L1502.7 115.7L1510.7 115.7L1511 116.0L1516.7 116.3L1517 116.7L1520.7 117.0L1525.3 118.3L1526.3 119.0L1527.3 119.0L1534.7 122.7L1540.3 126.7L1544 130.3L1549 137.0L1549 137.7L1551.3 141.7L1551.7 143.3L1552.7 145.0L1553 147.0L1554 149.0L1554.3 152.0L1555 153.3L1555 155.0L1555.3 155.3L1555.3 158.3L1555.7 158.7L1556 164.0L1556.3 164.3L1556.3 283.0L1556.7 283.3L1599.7 283.3L1600 282.7L1600 164.7L1599.7 164.3L1599.7 157.7L1599.3 157.3L1599 151.7L1598.7 151.3L1598.7 147.3L1597.7 144.0L1597.3 140.0L1596.3 137.3L1596 134.7L1595.3 133.7L1595 131.0L1591.3 121.3L1590.3 120.0L1590.3 119.3L1588 114.7L1584.3 109.0L1579.3 102.7Z', 1503.5],
]

// Mot-symbole animé. « drop » : chaque lettre tombe à sa place avec un rebond. « burst » : les lettres jaillissent
// du centre vers l'extérieur, vite puis lentement.
const LOGO_ORDER = LOGO_LETTERS.map(([, cx], i) => [Math.abs(cx - LOGO_W / 2), i]).sort((a, b) => a[0] - b[0]).map(([, i]) => i)

function Wordmark({ t, start, width, color = C.fg, step = 0.09, mode = 'drop' }) {
  return (
    <svg width={width} height={(width * LOGO_H) / LOGO_W} viewBox={`0 0 ${LOGO_W} ${LOGO_H}`} style={{ display: 'block', overflow: 'visible' }}>
      {LOGO_LETTERS.map(([d, cx], i) => {
        let transform
        let opacity
        if (mode === 'burst') {
          const k = eOutExpo(prog(t, start + LOGO_ORDER.indexOf(i) * 0.045, 0.7))
          opacity = clamp(k * 3)
          transform = `translate(${(1 - k) * (LOGO_W / 2 - cx) * 0.8} ${(1 - k) * 40}) translate(${cx} 190) scale(${lerp(0.15, 1, k)}) translate(${-cx} -190)`
        } else {
          const p = prog(t, start + i * step, 0.55)
          opacity = clamp(p * 2.5)
          transform = `translate(0 ${(1 - eBack(p)) * -170}) rotate(${(1 - p) * -16} ${cx} ${LOGO_H / 2})`
        }
        return (
          <g key={i} opacity={opacity} transform={transform}>
            <path d={d} fill={color} fillRule="evenodd" />
          </g>
        )
      })}
    </svg>
  )
}

// Volutes de vapeur au-dessus du point du « i »
function Steam({ t, start, x, y, color, scale = 1 }) {
  if (t < start) return null
  return [0, 1, 2].map((i) => {
    const k = ((t - start + i * 0.55) % 1.7) / 1.7
    return (
      <div key={i} style={abs(x - 8 * scale + (i - 1) * 20 * scale, y - k * 70 * scale, { opacity: Math.sin(k * Math.PI) * 0.6 })}>
        <svg width={16 * scale} height={40 * scale} viewBox="0 0 16 40">
          <path d="M8 38c-6-6 6-12 0-18s6-12 0-18" stroke={color} strokeWidth="3" fill="none" strokeLinecap="round" />
        </svg>
      </div>
    )
  })
}

/* ─── Décor commun ─────────────────────────────────────────────────── */
const BEANS = Array.from({ length: 12 }, (_, i) => ({
  x: (i * 197 + 61) % W,
  y: (i * 131 + 40) % H,
  s: 14 + ((i * 7) % 12),
  sp: 6 + ((i * 5) % 9),
  r: (i * 47) % 360,
}))

function Bean({ size, color }) {
  return (
    <svg width={size} height={size * 1.3} viewBox="0 0 20 26" style={{ display: 'block' }}>
      <ellipse cx="10" cy="13" rx="9" ry="12" fill={color} />
      <path d="M10 2c-3 4-3 8 0 11s3 7 0 11" stroke="rgba(255,255,255,.55)" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </svg>
  )
}

const OUTRO_AT = 31.2

function Background({ t }) {
  const outro = t >= OUTRO_AT
  return (
    <div style={{ position: 'absolute', inset: 0, background: outro ? C.accent : C.bg, overflow: 'hidden' }}>
      <div style={{
        position: 'absolute', inset: -40,
        backgroundImage: `radial-gradient(${outro ? 'rgba(255,255,255,.18)' : 'rgba(26,26,24,.08)'} 1.3px, transparent 1.4px)`,
        backgroundSize: '28px 28px',
        transform: `translate(${-(t * 9) % 28}px, ${-(t * 9) % 28}px)`,
      }} />
      {[0, 1, 2].map((i) => (
        <div key={i} style={{
          position: 'absolute', width: 520, height: 520, borderRadius: '50%',
          background: outro ? 'rgba(255,255,255,.22)' : 'rgba(232,81,14,.13)', filter: 'blur(70px)',
          left: 200 + i * 380 + Math.sin(t * 0.5 + i * 2) * 120,
          top: 80 + Math.cos(t * 0.4 + i * 1.7) * 160 + (i % 2) * 200,
        }} />
      ))}
      {BEANS.map((b, i) => (
        <div key={i} style={{
          position: 'absolute', left: b.x, top: ((b.y - t * b.sp) % (H + 60) + H + 60) % (H + 60) - 30,
          transform: `rotate(${b.r + t * (12 + i)}deg)`, opacity: outro ? 0.35 : 0.13,
        }}>
          <Bean size={b.s} color={outro ? '#fff' : C.accentInk} />
        </div>
      ))}
    </div>
  )
}

// Repères de la timeline (contrôles) : les moments où une scène se transforme en la suivante
const BEATS = [4.1, 9.3, 15.2, 21, 26.1, OUTRO_AT]

// Une scène : visible sur [from, to), avec une caméra qui respire (poussée lente, nulle aux bords pour que les
// éléments transformés d'une scène à l'autre restent alignés) et des coups de zoom sur les temps forts.
function Scene({ t, from, to, drift = 0.03, punches = [], origin = '50% 45%', children }) {
  if (t < from || t >= to) return null
  const k = (t - from) / (to - from)
  const zoom = 1 + drift * Math.sin(k * Math.PI) + punches.reduce((sum, at) => sum + punch(t, at), 0)
  return (
    <div style={{ position: 'absolute', inset: 0, transform: `scale(${zoom})`, transformOrigin: origin }}>
      {children}
    </div>
  )
}

const Layer = ({ style, children }) => <div style={{ position: 'absolute', inset: 0, ...style }}>{children}</div>

// Typographie cinétique : chaque mot monte de derrière un masque, vite puis lentement.
// parts : [["texte", style?], …] ; "\n" force un retour à la ligne.
function Kinetic({ t, start, parts, stagger = 0.055, dur = 0.75 }) {
  let n = 0
  return parts.flatMap(([text, style], pi) => {
    if (text === '\n') return [<br key={`br${pi}`} />]
    return text.split(' ').filter(Boolean).map((word, wi) => {
      const k = eOutExpo(prog(t, start + n++ * stagger, dur))
      return (
        <span key={`${pi}-${wi}`} style={{ display: 'inline-block', overflow: 'hidden', verticalAlign: 'top',
          padding: '0 0.08em 0.14em 0', margin: '0 0.17em -0.14em 0' }}>
          <span style={{ display: 'inline-block', transform: `translateY(${(1 - k) * 110}%) rotate(${(1 - k) * 8}deg)`,
            transformOrigin: '0 100%', ...style }}>
            {word}
          </span>
        </span>
      )
    })
  })
}

const Kicker = ({ children, color = C.accent, style }) => (
  <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: 15, letterSpacing: '0.16em', color, textTransform: 'uppercase', ...style }}>
    {children}
  </div>
)

const Card = ({ style, children }) => (
  <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 18, boxShadow: SHADOW, ...style }}>
    {children}
  </div>
)

const Caret = ({ t, color = C.accent, h = 26 }) => (
  <span style={{ display: 'inline-block', width: 2.5, height: h, background: color, marginLeft: 2,
    verticalAlign: 'middle', opacity: Math.sin(t * 9) > 0 ? 1 : 0 }} />
)

const Skeleton = ({ w, h = 12 }) => (
  <div style={{ width: w, height: h, borderRadius: 6, background: C.surface3 }} />
)

/* ─── Scène 1 : intro (0 – 4 s) ────────────────────────────────────── */
// Un point tombe, rebondit, s'étire en trait ; le logo en jaillit. Puis la caméra plonge dans le point du « i ».
const INTRO_WORD_W = 780
const INTRO_LEFT = (W - INTRO_WORD_W) / 2
const INTRO_TOP = 200
const LOGO_SCALE = INTRO_WORD_W / LOGO_W
const I_DOT = [INTRO_LEFT + LOGO_LETTERS[4][1] * LOGO_SCALE, INTRO_TOP + 28 * LOGO_SCALE]
const LINE_Y = INTRO_TOP + 190 * LOGO_SCALE

function Intro({ t }) {
  const fall = prog(t, 0.05, 0.55)
  const squash = Math.sin(prog(t, 0.47, 0.22) * Math.PI)
  const stretch = eInOutExpo(prog(t, 0.68, 0.4))
  const retract = eInOutExpo(prog(t, 1.05, 0.5))
  const dotW = lerp(30, INTRO_WORD_W + 40, stretch) * (1 - retract)
  const dotH = lerp(30, 8, stretch)
  const dotY = lerp(LINE_Y, LINE_Y + 82, retract)
  const dive = eInExpo(prog(t, 3.55, 0.55))
  return (
    <Layer style={{ transform: `translate(${(640 - I_DOT[0]) * eOutExpo(prog(t, 3.5, 0.5))}px, ${(360 - I_DOT[1]) * eOutExpo(prog(t, 3.5, 0.5))}px) scale(${1 + 70 * dive})`,
      transformOrigin: `${I_DOT[0]}px ${I_DOT[1]}px` }}>
      {fall > 0 && dotW > 0.5 && (
        <div style={abs(640 - dotW / 2, lerp(-60, dotY, eBounce(fall)) - dotH / 2, {
          width: dotW, height: dotH, borderRadius: 15, background: C.accent,
          transform: `scale(${1 + squash * 0.45}, ${1 - squash * 0.4})`, transformOrigin: '50% 100%' })} />
      )}
      <Steam t={t} start={1.7} x={I_DOT[0]} y={INTRO_TOP - 50} color={C.accent} />
      <div style={abs(INTRO_LEFT, INTRO_TOP)}>
        <Wordmark t={t} start={0.92} width={INTRO_WORD_W} mode="burst" />
      </div>
      <div style={abs(0, 402, { width: W, textAlign: 'center', fontFamily: SERIF, fontSize: 44, color: C.fg })}>
        <Kinetic t={t} start={1.45} parts={[["L'ERP"], ['libre', { color: C.accent, fontStyle: 'italic' }], ['et modulaire des petites entreprises.']]} />
      </div>
      <div style={abs(0, 496, { width: W, display: 'flex', justifyContent: 'center', gap: 14 })}>
        {[
          ['github', 'Open source · AGPL-3.0'],
          ['server', 'Auto-hébergé'],
          ['sparkle', 'IA optionnelle'],
        ].map(([ic, label], i) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', gap: 9, padding: '11px 18px', borderRadius: 999,
            background: i === 2 ? C.accentSoft : C.surface, border: `1px solid ${i === 2 ? 'rgba(232,81,14,.25)' : C.border}`,
            fontFamily: SANS, fontWeight: 600, fontSize: 18, color: i === 2 ? C.accentInk : C.fg,
            ...enter(t, 2.1 + i * 0.1, 0.6, { y: 40, s: 0.6, blur: 6 }),
          }}>
            <Icon name={ic} size={19} color={i === 2 ? C.accent : C.fg} /> {label}
          </div>
        ))}
      </div>
    </Layer>
  )
}

// Passage au noir : la plongée dans le point du « i » remplit l'écran, la scène suivante en ressort.
function Blackout({ t }) {
  const o = t < 4.1 ? eInExpo(prog(t, 3.85, 0.25)) : 1 - eOutExpo(prog(t, 4.1, 0.45))
  if (o <= 0) return null
  return <div style={{ position: 'absolute', inset: 0, background: C.fg, opacity: o }} />
}

/* ─── Scène 2 : les trucs chiants (4 – 9 s) ────────────────────────── */
// Les tâches tombent et s'empilent… puis sont aspirées par le noyau de l'IA.
const CHORES = [
  ['mail', 'Relancer Jean Martin (3e fois)', 'F-2026-031 · 45 jours de retard', 640, 120, -6],
  ['folder', 'Classer 47 justificatifs', 'Photos floues, PDF nommés « scan »', 875, 200, 5],
  ['percent', 'Calculer la TVA du trimestre', 'Collectée, déductible, balance…', 610, 290, 3],
  ['doc', 'Rédiger le devis Dupont', 'Mentions légales, numérotation…', 860, 370, -4],
  ['bank', "Déclarer l'URSSAF", 'Chiffre encaissé, cotisations', 640, 460, 7],
  ['box', 'Saisir la réception fournisseur', 'Et mettre le stock à jour', 880, 540, -3],
]
const CORE = [360, 370] // le noyau de l'IA, futur centre de la barre de saisie
const ABSORB_AT = 8.5
const absorbArrival = (i) => ABSORB_AT + i * 0.06 + 0.42

function Chores({ t }) {
  const shake = prog(t, 7.6, 0.2) * (1 - prog(t, 8.2, 0.2))
  const minutes = Math.round(400 * eOut(prog(t, 6.0, 1.6)))
  return (
    <Layer style={enter(t, 4.08, 0.7, { s: 1.22, blur: 14 })}>
      <Layer style={leave(t, ABSORB_AT - 0.1, 0.4, { x: -320, blur: 14 })}>
        <Kicker style={abs(80, 92)}><Kinetic t={t} start={4.2} parts={[["Le quotidien d'une petite entreprise"]]} stagger={0.03} /></Kicker>
        {['Facturer.', 'Relancer.', 'Classer.', 'Déclarer.'].map((w, i) => (
          <div key={w} style={abs(78, 128 + i * 70, { fontFamily: SERIF, fontSize: 72, lineHeight: 1, color: C.fg })}>
            <Kinetic t={t} start={4.3 + i * 0.14} parts={[[w]]} dur={0.7} />
          </div>
        ))}
        <div style={abs(80, 418, { fontFamily: SANS, fontSize: 26, fontWeight: 500, color: C.muted, ...enter(t, 5.3, 0.6, { x: -40, blur: 6 }) })}>
          Bref, <span style={{ color: C.fg, fontWeight: 700, position: 'relative' }}>
            les trucs chiants
            <svg width="210" height="14" viewBox="0 0 210 14" style={{ position: 'absolute', left: 0, bottom: -10 }}>
              <path d="M3 9c40-6 80-8 120-4s60 2 84-3" stroke={C.accent} strokeWidth="4" fill="none" strokeLinecap="round"
                pathLength="1" strokeDasharray="1" strokeDashoffset={1 - eOutExpo(prog(t, 5.7, 0.6))} />
            </svg>
          </span>.
        </div>
        <div style={abs(80, 500, enter(t, 5.9, 0.6, { y: 30, blur: 8 }))}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: SANS, fontSize: 17, fontWeight: 600, color: C.muted }}>
            <Icon name="clock" size={18} color={C.muted} /> Temps perdu cette semaine
          </div>
          <div style={{ fontFamily: SERIF, fontSize: 92, lineHeight: 1.05, color: C.accent, fontVariantNumeric: 'tabular-nums',
            transform: `rotate(${shake * Math.sin(t * 50) * 1.5}deg) scale(${1 + punch(t, 7.6, 0.12)})`, transformOrigin: '0 50%' }}>
            {Math.floor(minutes / 60)} h {String(minutes % 60).padStart(2, '0')}
          </div>
        </div>
      </Layer>
      {CHORES.map(([ic, title, sub, x, y, rot], i) => {
        const s = 4.45 + i * 0.28
        const p = prog(t, s, 0.95)
        const suck = eInExpo(prog(t, ABSORB_AT + i * 0.06, 0.42))
        if (p <= 0 || suck >= 0.97) return null
        const yy = lerp(-160, y, eBounce(p))
        const jx = shake * Math.sin(t * 55 + i * 1.7) * 4
        const jr = shake * Math.sin(t * 47 + i) * 2.2
        return (
          <Card key={title} style={abs(lerp(x + jx, CORE[0] - 170, suck), lerp(yy, CORE[1] - 37, suck), {
            width: 340, padding: '15px 18px', display: 'flex', alignItems: 'center', gap: 14,
            transform: `rotate(${lerp(rot * 4, rot, eOut(p)) + jr + suck * 300}deg) scale(${lerp(1, 0.04, suck)})`,
            filter: suck > 0 ? `blur(${suck * 6}px)` : 'none',
          })}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: C.accentSoft, display: 'grid', placeItems: 'center' }}>
              <Icon name={ic} size={22} color={C.accent} />
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: 17, color: C.fg, whiteSpace: 'nowrap' }}>{title}</div>
              <div style={{ fontFamily: SANS, fontSize: 14, color: C.muted, marginTop: 2, whiteSpace: 'nowrap' }}>{sub}</div>
            </div>
            {i % 2 === 0 && (
              <div style={{ position: 'absolute', top: -9, right: -9, width: 24, height: 24, borderRadius: 12, background: C.bad,
                color: '#fff', fontFamily: SANS, fontWeight: 800, fontSize: 15, display: 'grid', placeItems: 'center', ...pop(t, s + 0.7, 0.35) }}>
                !
              </div>
            )}
          </Card>
        )
      })}
    </Layer>
  )
}

/* ─── Scène 3 : un devis en une phrase (9 – 15 s) ──────────────────── */
// Le noyau de l'IA avale les tâches, puis s'ouvre en barre de saisie ; à la fin, le devis se replie en panneau.
const PROMPT = 'Mission logo pour Jean Martin, 800 €, livraison le 15'
const PROMPT_START = 9.9
const PROMPT_CPS = 28
const QUOTE_RECT = [700, 150, 500, 440]
const PANEL_RECTS = [[80, 176, 352, 430], [464, 176, 352, 430], [848, 176, 352, 430]]
const BAR_RECT = [80, 330, 560, 80]

function QuoteFromSentence({ t }) {
  const sent = prog(t, 11.9, 0.25)
  const total = 800 * eOutExpo(prog(t, 13.15, 0.9))
  const fields = [
    ['Client', 'Jean Martin', 12.25],
    ['Livraison', '15 novembre 2026', 12.5],
    ['Échéance', 'À réception', 12.75],
  ]
  // Noyau → barre
  const born = eBack(prog(t, ABSORB_AT - 0.05, 0.35))
  const gulps = CHORES.reduce((sum, _, i) => sum + punch(t, absorbArrival(i), 0.16), 0)
  const morph = eInOutExpo(prog(t, 9.3, 0.55))
  const bar = lerpRect([CORE[0] - 36, CORE[1] - 36, 72, 72], BAR_RECT, morph)
  const barIn = prog(t, 9.7, 0.25)
  // Devis → panneau central
  const fold = eInOutExpo(prog(t, 14.62, 0.5))
  const card = lerpRect(QUOTE_RECT, PANEL_RECTS[1], fold)
  const cardContent = 1 - prog(t, 14.5, 0.14)
  return (
    <Layer>
      <Layer style={leave(t, 14.5, 0.42, { y: -140, blur: 14 })}>
        <Kicker style={abs(80, 86)}><Kinetic t={t} start={9.2} parts={[["Avec l'IA"]]} /></Kicker>
        <div style={abs(78, 116, { fontFamily: SERIF, fontSize: 62, lineHeight: 1.05, color: C.fg, width: 600 })}>
          <Kinetic t={t} start={9.3} parts={[['Les trucs chiants ?'], ['\n'], ["L'IA s'en charge.", { color: C.accent }]]} />
          <div style={{ height: 4, width: 452, borderRadius: 2, background: C.accent, marginTop: -6,
            transformOrigin: 'left', transform: `scaleX(${eOutExpo(prog(t, 9.85, 0.6))})` }} />
        </div>
      </Layer>

      <Layer style={leave(t, 14.58, 0.42, { x: -420, blur: 16 })}>
        {/* Noyau de l'IA qui devient la barre de saisie */}
        {t >= ABSORB_AT - 0.05 && (
          <div style={abs(bar[0], bar[1], { width: bar[2], height: bar[3], borderRadius: lerp(36, 18, morph),
            transform: `scale(${born * (1 + gulps)})`, boxShadow: SHADOW, overflow: 'hidden' })}>
            <div style={{ position: 'absolute', inset: 0, background: C.surface, border: `1px solid ${sent > 0 && sent < 1 ? C.accent : C.border}`,
              borderRadius: 'inherit', opacity: morph }} />
            <div style={{ position: 'absolute', inset: 0, background: C.accent, opacity: 1 - morph }} />
            {morph < 1 && (
              <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', opacity: 1 - morph,
                transform: `rotate(${t * 220}deg)` }}>
                <Icon name="sparkle" size={30} color="#fff" />
              </div>
            )}
            <div style={{ position: 'absolute', inset: 0, padding: '0 18px', display: 'flex', alignItems: 'center', gap: 14, opacity: barIn }}>
              <div style={{ transform: `rotate(${t * 40}deg) scale(${1 + Math.sin(t * 6) * 0.08})` }}>
                <Icon name="sparkle" size={26} color={C.accent} />
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center',
                justifyContent: typed(PROMPT, t, PROMPT_START, PROMPT_CPS).length > 34 ? 'flex-end' : 'flex-start',
                fontFamily: SANS, fontSize: 20, fontWeight: 500, color: t < PROMPT_START ? C.subtle : C.fg, whiteSpace: 'nowrap', overflow: 'hidden' }}>
                {t < PROMPT_START ? 'Décrivez votre devis…' : typed(PROMPT, t, PROMPT_START, PROMPT_CPS)}
                {t >= PROMPT_START && t < 12 && <Caret t={t} />}
              </div>
              <div style={{ width: 46, height: 46, borderRadius: 12, display: 'grid', placeItems: 'center', flexShrink: 0,
                background: typingDone(PROMPT, t, PROMPT_START, PROMPT_CPS) ? C.accent : C.surface3,
                transform: `scale(${1 - Math.sin(sent * Math.PI) * 0.18})` }}>
                <Icon name="arrow" size={22} color="#fff" />
              </div>
            </div>
          </div>
        )}
        <div style={abs(82, 432, { width: 520, fontFamily: SANS, fontSize: 19, lineHeight: 1.45, color: C.muted, ...enter(t, 12.35, 0.6, { y: 20, blur: 6 }) })}>
          Une phrase suffit : client, lignes, dates et mentions légales sont remplis. <b style={{ color: C.fg }}>Vous relisez, vous envoyez.</b>
        </div>
        {/* La phrase part vers le devis */}
        {Array.from({ length: 9 }, (_, i) => {
          const k = eInOutExpo(prog(t, 11.95 + i * 0.035, 0.5))
          if (k <= 0 || k >= 1) return null
          const x = lerp(610, 700, k)
          const y = lerp(370, 300, k) - Math.sin(k * Math.PI) * (50 + i * 12)
          return <div key={i} style={abs(x, y, { width: 10, height: 10, borderRadius: 5, background: C.accent, opacity: 1 - k * 0.4 })} />
        })}
      </Layer>

      {/* Devis (il se replie ensuite en panneau « Relances ») */}
      {t < 15.12 && (
        <div style={abs(card[0], card[1], { width: card[2], height: card[3], ...enter(t, 9.6, 0.8, { x: 160, r: 5, s: 0.9, blur: 12 }) })}>
          <Card style={{ position: 'absolute', inset: 0, padding: 28 }}>
            <div style={{ opacity: cardContent }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 24, color: C.fg, letterSpacing: '-0.02em' }}>Devis</div>
                  <div style={{ fontFamily: MONO, fontSize: 14, color: C.muted, marginTop: 2 }}>D-2026-042</div>
                </div>
                <div style={{ padding: '6px 12px', borderRadius: 999, fontFamily: SANS, fontWeight: 700, fontSize: 13,
                  background: t > 13.95 ? C.goodSoft : C.surface2, color: t > 13.95 ? C.good : C.muted }}>
                  {t > 13.95 ? 'Prêt' : 'Brouillon'}
                </div>
              </div>
              <div style={{ height: 1, background: C.border, margin: '20px 0' }} />
              {fields.map(([label, value, s]) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', height: 34 }}>
                  <div style={{ width: 120, fontFamily: SANS, fontSize: 15, color: C.muted }}>{label}</div>
                  {t < s ? <Skeleton w={150} /> : (
                    <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 17, color: C.fg, ...appear(t, s, 0.35, 10),
                      background: `linear-gradient(90deg, ${C.accentSoft} ${100 - prog(t, s + 0.2, 0.6) * 100}%, transparent 0)`, padding: '2px 6px', marginLeft: -6, borderRadius: 6 }}>
                      {value}
                    </div>
                  )}
                </div>
              ))}
              <div style={{ marginTop: 16, borderRadius: 12, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 50px 110px 110px', padding: '10px 14px', background: C.surface2,
                  fontFamily: SANS, fontSize: 13, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  <span>Désignation</span><span>Qté</span><span style={{ textAlign: 'right' }}>PU HT</span><span style={{ textAlign: 'right' }}>Total</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 50px 110px 110px', padding: '13px 14px', alignItems: 'center',
                  fontFamily: SANS, fontSize: 16, color: C.fg, height: 48 }}>
                  {t < 12.95 ? (<><Skeleton w={130} /><Skeleton w={20} /><Skeleton w={70} /><Skeleton w={70} /></>) : (
                    <>
                      <span style={{ fontWeight: 600, ...appear(t, 12.95, 0.3, 8) }}>Mission logo</span>
                      <span style={appear(t, 13.0, 0.3, 8)}>1</span>
                      <span style={{ textAlign: 'right', ...appear(t, 13.05, 0.3, 8) }}>800,00 €</span>
                      <span style={{ textAlign: 'right', fontWeight: 600, ...appear(t, 13.1, 0.3, 8) }}>800,00 €</span>
                    </>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 20 }}>
                <div style={{ fontFamily: SANS, fontSize: 13, color: C.subtle, maxWidth: 240, lineHeight: 1.4, ...appear(t, 13.55, 0.4, 6) }}>
                  TVA non applicable, art. 293 B du CGI
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontFamily: SANS, fontSize: 14, color: C.muted }}>Total HT</div>
                  <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 34, color: C.fg, letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums' }}>
                    {euro(total)}
                  </div>
                </div>
              </div>
            </div>
          </Card>
          <div style={abs(196, -30, {
            padding: '10px 16px', border: `3px solid ${C.accent}`, borderRadius: 12, color: C.accent, background: 'rgba(255,255,255,.92)',
            fontFamily: SANS, fontWeight: 800, fontSize: 18, letterSpacing: '.04em', textTransform: 'uppercase', display: 'flex', gap: 8, alignItems: 'center',
            ...(t < 14.5 ? pop(t, 13.95, 0.4, 'rotate(8deg)') : leave(t, 14.5, 0.35, { y: -90, r: 30, s: 1.4, blur: 8 })),
          })}>
            <Icon name="check" size={20} color={C.accent} stroke={3} /> Prêt à envoyer
          </div>
        </div>
      )}
    </Layer>
  )
}

/* ─── Scène 4 : classer, relancer, analyser (15 – 21 s) ────────────── */
function PanelHead({ icon, title }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
      <div style={{ width: 36, height: 36, borderRadius: 10, background: C.accentSoft, display: 'grid', placeItems: 'center' }}>
        <Icon name={icon} size={19} color={C.accent} />
      </div>
      <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: 17, color: C.fg, lineHeight: 1.2 }}>{title}</div>
    </div>
  )
}

function Receipts({ t }) {
  const drop = prog(t, 15.95, 0.7)
  const scan = prog(t, 16.65, 0.75)
  const newName = '2026-10_Boulonnerie-Ouest_142,80.pdf'
  return (
    <>
      <PanelHead icon="folder" title="Justificatifs classés tout seuls" />
      <div style={{ position: 'relative', height: 150, borderRadius: 14, border: `2px dashed ${drop >= 1 ? C.accent : C.borderStrong}`,
        background: drop >= 1 ? C.accentSoft : C.surface2, overflow: 'hidden' }}>
        {drop > 0 && (
          <div style={abs(131, lerp(-110, 22, eBounce(drop)), { width: 74, height: 96, borderRadius: 8, background: '#fff',
            border: `1px solid ${C.border}`, boxShadow: SHADOW, padding: 10, transform: `rotate(${(1 - drop) * 20}deg)` })}>
            <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 11, color: C.bad }}>PDF</div>
            {[46, 36, 50, 28].map((w, i) => <div key={i} style={{ width: w, height: 5, borderRadius: 3, background: C.surface3, marginTop: 7 }} />)}
          </div>
        )}
        {scan > 0 && scan < 1 && (
          <div style={abs(110, lerp(18, 122, Math.abs(Math.sin(scan * Math.PI * 1.5))), { width: 116, height: 3, borderRadius: 2,
            background: C.accent, boxShadow: `0 0 18px 4px rgba(232,81,14,.45)` })} />
        )}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 16, minHeight: 76 }}>
        {['Boulonnerie Ouest', '142,80 € TTC', 'Fournitures', 'Échéance 30/11'].map((chip, i) => (
          <div key={chip} style={{ padding: '6px 11px', borderRadius: 999, background: i === 1 ? C.accentSoft : C.surface2,
            color: i === 1 ? C.accentInk : C.fg, fontFamily: SANS, fontWeight: 600, fontSize: 14, ...pop(t, 17.35 + i * 0.18, 0.4) }}>
            {chip}
          </div>
        ))}
      </div>
      <div style={{ fontFamily: MONO, fontSize: 12.5, marginTop: 12, height: 20, whiteSpace: 'nowrap', color: C.fg }}>
        {t < 18.55 ? (
          <span style={{ color: C.muted, textDecoration: t > 18.3 ? 'line-through' : 'none', ...appear(t, 16.4, 0.3, 6) }}>scan_0042.jpg</span>
        ) : (
          <span>{typed(newName, t, 18.55, 42)}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 12, fontFamily: SANS, fontSize: 14, fontWeight: 600, color: C.good, ...appear(t, 19.5, 0.4, 8) }}>
        <Icon name="lock" size={16} color={C.good} /> Chiffré AES-256-GCM et rangé
      </div>
    </>
  )
}

function Reminders({ t }) {
  const levels = [
    ['Rappel amical', 16.55],
    ['Relance ferme', 17.3],
    ['Mise en demeure amiable', 18.05],
  ]
  const fill = eInOutExpo(prog(t, 16.55, 1.5))
  return (
    <>
      <PanelHead icon="mail" title="Relances d'impayés rédigées" />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderRadius: 12, background: C.surface2 }}>
        <div style={{ fontFamily: SANS, fontSize: 14, fontWeight: 600, color: C.fg }}>F-2026-031 · 800,00 €</div>
        <div style={{ fontFamily: SANS, fontSize: 12.5, fontWeight: 700, color: C.bad, background: C.badSoft, padding: '3px 8px', borderRadius: 999 }}>45 j de retard</div>
      </div>
      <div style={{ position: 'relative', marginTop: 18, paddingLeft: 6 }}>
        <div style={abs(15, 12, { width: 3, height: 76, background: C.surface3, borderRadius: 2 })} />
        <div style={abs(15, 12, { width: 3, height: 76 * fill, background: C.accent, borderRadius: 2 })} />
        {levels.map(([label, s]) => {
          const on = t >= s
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 12, height: 38, position: 'relative' }}>
              <div style={{ width: 21, height: 21, borderRadius: 11, background: on ? C.accent : '#fff', border: `3px solid ${on ? C.accent : C.borderStrong}`,
                transform: `scale(${on ? 1 + Math.sin(prog(t, s, 0.35) * Math.PI) * 0.45 : 1})` }} />
              <div style={{ fontFamily: SANS, fontSize: 15.5, fontWeight: on ? 700 : 500, color: on ? C.fg : C.subtle }}>{label}</div>
            </div>
          )
        })}
      </div>
      <div style={{ marginTop: 16, padding: 14, borderRadius: 12, border: `1px solid ${C.border}`, background: '#fff', height: 100 }}>
        <div style={{ fontFamily: SANS, fontSize: 14.5, color: C.fg, height: 20 }}>{typed('Bonjour Jean,', t, 18.5, 30)}</div>
        {[250, 210, 236, 120].map((w, i) => (
          <div key={i} style={{ width: w * eOutExpo(prog(t, 19.0 + i * 0.14, 0.45)), height: 7, borderRadius: 4, background: C.surface3, marginTop: 9 }} />
        ))}
      </div>
      <div style={{ marginTop: 12, fontFamily: SANS, fontSize: 13.5, color: C.muted, ...appear(t, 19.75, 0.4, 8) }}>
        Max une par semaine, notifiée à chaque envoi
      </div>
    </>
  )
}

function MyViews({ t }) {
  const months = ['mai', 'juin', 'juil.', 'août', 'sept.', 'oct.']
  const vals = [4.2, 5.1, 3.8, 6.4, 7.0, 8.3]
  const spend = [2.4, 2.9, 2.2, 3.1, 2.6, 3.4]
  const line = eInOutExpo(prog(t, 19.25, 0.8))
  const chartH = 150
  const pts = spend.map((v, i) => `${20 + i * 50},${chartH - (v / 9) * chartH}`).join(' ')
  const p2 = '+ ajoute mes dépenses'
  return (
    <>
      <PanelHead icon="chart" title="Mes vues, à la demande" />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderRadius: 12, background: C.surface2, height: 40 }}>
        <Icon name="sparkle" size={17} color={C.accent} />
        <div style={{ fontFamily: SANS, fontSize: 14.5, fontWeight: 500, color: C.fg, whiteSpace: 'nowrap' }}>
          {t < 18.55 ? typed('Mon CA par mois', t, 16.2, 20) : typed(p2, t, 18.55, 24)}
        </div>
      </div>
      <div style={{ position: 'relative', height: chartH, marginTop: 24 }}>
        {[0, 1, 2].map((g) => <div key={g} style={abs(0, (chartH / 3) * g, { width: '100%', height: 1, background: C.border })} />)}
        {vals.map((v, i) => {
          const k = eBack(prog(t, 17.0 + i * 0.09, 0.55))
          const h = (v / 9) * chartH * Math.max(0, k)
          return (
            <div key={i} style={abs(5 + i * 50, chartH - h, { width: 30, height: h, borderRadius: '7px 7px 3px 3px',
              background: i === 5 ? C.accent : 'rgba(232,81,14,.32)' })} />
          )
        })}
        <div style={abs(222, chartH - (8.3 / 9) * chartH - 30, { fontFamily: SANS, fontWeight: 800, fontSize: 14, color: C.accentInk, ...pop(t, 17.85, 0.4) })}>8,3 k€</div>
        {line > 0 && (
          <svg width="300" height={chartH} style={abs(0, 0)}>
            <polyline points={pts} fill="none" stroke={C.fg} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round"
              pathLength="1" strokeDasharray="1" strokeDashoffset={1 - line} />
          </svg>
        )}
      </div>
      <div style={{ display: 'flex', marginTop: 8 }}>
        {months.map((m) => <div key={m} style={{ width: 50, textAlign: 'left', paddingLeft: 3, fontFamily: SANS, fontSize: 12.5, color: C.muted }}>{m}</div>)}
      </div>
      <div style={{ marginTop: 18, fontFamily: SANS, fontSize: 13.5, lineHeight: 1.4, color: C.muted, ...appear(t, 19.8, 0.4, 8) }}>
        L'IA compose la page. <b style={{ color: C.fg }}>Elle ne voit jamais vos chiffres.</b>
      </div>
    </>
  )
}

// L'interrupteur géant au centre de l'écran (2 × l'interrupteur de la scène 5)
const TOGGLE_RECT = [536, 304, 208, 112]
const MERGE_AT = 20.4

function Delegated({ t }) {
  const panels = [Receipts, Reminders, MyViews]
  const entries = [{ x: -560, r: -8 }, null, { x: 560, r: 8 }]
  const contentOut = 1 - prog(t, MERGE_AT - 0.1, 0.15)
  return (
    <Layer>
      <div style={abs(78, 72, { fontFamily: SERIF, fontSize: 58, lineHeight: 1, color: C.fg, ...leave(t, MERGE_AT - 0.15, 0.4, { y: -120, blur: 12 }) })}>
        <Kinetic t={t} start={15.0} parts={[['Classer, relancer, analyser :'], ['délégué.', { color: C.accent, fontStyle: 'italic' }]]} stagger={0.07} />
      </div>
      {panels.map((Panel, i) => {
        if (i === 1 && t < 15.12) return null // le devis de la scène précédente est en train de devenir ce panneau
        const merge = eInOutExpo(prog(t, MERGE_AT + i * 0.05, 0.5))
        const rect = lerpRect(PANEL_RECTS[i], TOGGLE_RECT, merge)
        const intro = entries[i] ? enter(t, 15.0 + i * 0.05, 0.75, { ...entries[i], blur: 16 }) : {}
        return (
          <div key={i} style={abs(rect[0], rect[1], { width: rect[2], height: rect[3], ...intro })}>
            <Card style={{ position: 'absolute', inset: 0, borderRadius: lerp(18, 56, merge), overflow: 'hidden' }}>
              <div style={{ padding: 22, opacity: contentOut, ...(i === 1 ? enter(t, 15.15, 0.45, { y: 24, blur: 6 }) : {}) }}>
                <Panel t={t} />
              </div>
              <div style={{ position: 'absolute', inset: 0, background: C.accent, opacity: eInExpo(prog(t, MERGE_AT + 0.15, 0.35)) }} />
            </Card>
          </div>
        )
      })}
    </Layer>
  )
}

/* ─── Scène 5 : et sans IA ? (21 – 26 s) ───────────────────────────── */
// Ralenti : l'interrupteur géant se coupe, file se ranger, et le devis se remplit à la main.
const CURSOR = [
  [22.55, 1230, 690],
  [22.95, 800, 281],
  [23.4, 830, 361],
  [24.1, 709, 441],
  [24.45, 865, 441],
  [25.2, 1096, 520],
]
function cursorAt(t) {
  if (t <= CURSOR[0][0]) return [CURSOR[0][1], CURSOR[0][2]]
  for (let i = 1; i < CURSOR.length; i++) {
    const [t1, x1, y1] = CURSOR[i]
    const [t0, x0, y0] = CURSOR[i - 1]
    if (t <= t1) {
      const k = eInOutExpo((t - t0) / (t1 - t0))
      return [lerp(x0, x1, k), lerp(y0, y1, k) - Math.sin(k * Math.PI) * 30]
    }
  }
  const last = CURSOR[CURSOR.length - 1]
  return [last[1], last[2]]
}

function Field({ label, value, w, active, mono, computed, flash }) {
  return (
    <div style={{ width: w }}>
      <div style={{ fontFamily: SANS, fontSize: 13, fontWeight: 600, color: C.muted, marginBottom: 6 }}>{label}</div>
      <div style={{ height: 44, borderRadius: 10, padding: '0 13px', display: 'flex', alignItems: 'center', fontFamily: mono ? MONO : SANS,
        fontSize: 16.5, fontWeight: computed ? 800 : 500, color: C.fg, whiteSpace: 'nowrap', overflow: 'hidden',
        border: `1.5px solid ${active ? C.accent : C.border}`, boxShadow: active ? `0 0 0 4px ${C.accentSoft}` : 'none',
        background: computed ? (flash ? C.goodSoft : C.surface2) : '#fff', transition: 'none' }}>
        {value}
      </div>
    </div>
  )
}

const FLIP_AT = 21.6
const PARK_AT = 22.05
const WHIP_AT = 25.75

function WithoutAI({ t }) {
  const flip = eBack(prog(t, FLIP_AT, 0.4))
  const off = t >= FLIP_AT + 0.12
  const settle = Math.sin(prog(t, 21.0, 0.3) * Math.PI) * (1 - prog(t, 21.0, 0.3))
  const park = eInOutExpo(prog(t, PARK_AT, 0.55))
  const tScale = lerp(2, 1, park) * (1 + settle * 0.08)
  const ripple = prog(t, FLIP_AT + 0.05, 0.6)
  const [cx, cy] = cursorAt(t)
  const clicks = CURSOR.slice(1).map((c) => c[0])
  const totalOn = t >= 24.85
  const pressed = t >= 25.2 && t < 25.4
  const badges = [
    ['check', 'Saisie classique, calculs faits par le serveur'],
    ['doc', 'Justificatifs lus en analyse locale'],
    ['mail', "Emails gardés dans la boîte d'envoi"],
    ['lock', 'Aucune donnée ne quitte votre serveur'],
  ]
  return (
    <Layer style={leave(t, WHIP_AT, 0.4, { x: -1500, blur: 22 })}>
      <Kicker style={abs(80, 86)}><Kinetic t={t} start={22.0} parts={[['Sans clé API, sans abonnement']]} stagger={0.035} /></Kicker>
      <div style={abs(78, 116, { fontFamily: SERIF, fontSize: 62, lineHeight: 1.05, color: C.fg })}>
        <Kinetic t={t} start={22.1} parts={[['Et sans IA ?'], ['\n'], ['Tout marche pareil.', { color: C.accent, fontStyle: 'italic' }]]} stagger={0.07} />
      </div>

      {/* Interrupteur IA : né de la fusion des panneaux, coupé au ralenti, puis rangé */}
      <div style={abs(80, 286, { width: 104, height: 56, transformOrigin: '0 0',
        transform: `translate(${lerp(TOGGLE_RECT[0] - 80, 0, park)}px, ${lerp(TOGGLE_RECT[1] - 286, 0, park)}px) scale(${tScale})` })}>
        {ripple > 0 && ripple < 1 && (
          <div style={{ position: 'absolute', inset: -ripple * 26, borderRadius: 999, border: `${3 - ripple * 2}px solid ${C.accent}`, opacity: 1 - ripple }} />
        )}
        <div style={{ position: 'absolute', inset: 0, borderRadius: 28, background: off ? C.borderStrong : C.accent }} />
        <div style={abs(lerp(52, 4, flip), 4, { width: 48, height: 48, borderRadius: 24, background: '#fff', boxShadow: '0 2px 8px rgba(0,0,0,.2)',
          display: 'grid', placeItems: 'center', ...pop(t, 21.02, 0.35) })}>
          <div style={{ transform: `rotate(${off ? 0 : t * 120}deg)` }}>
            <Icon name="sparkle" size={22} color={off ? C.subtle : C.accent} />
          </div>
        </div>
      </div>
      {/* Légende au centre pendant le ralenti */}
      <div style={abs(0, 438, { width: W, textAlign: 'center', ...leave(t, PARK_AT - 0.05, 0.3, { y: 40, blur: 8 }) })}>
        <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: 30, color: C.fg }}>
          <Kinetic t={t} start={21.1} parts={[['Assistant IA']]} />
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 22, marginTop: 4, color: off ? C.muted : C.accentInk,
          transform: `scale(${1 + punch(t, FLIP_AT + 0.12, 0.25)})` }}>
          {off ? 'Désactivé' : 'Activé'}
        </div>
      </div>
      <div style={abs(202, 288, enter(t, PARK_AT + 0.4, 0.5, { x: -30, blur: 6 }))}>
        <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: 20, color: C.fg }}>Assistant IA</div>
        <div style={{ fontFamily: SANS, fontSize: 16, color: C.muted, fontWeight: 600 }}>Désactivé</div>
      </div>
      {badges.map(([ic, label], i) => (
        <div key={label} style={abs(80, 378 + i * 54, { display: 'flex', alignItems: 'center', gap: 12, ...enter(t, 22.6 + i * 0.13, 0.6, { x: -80, blur: 10 }) })}>
          <div style={{ width: 34, height: 34, borderRadius: 17, background: C.goodSoft, display: 'grid', placeItems: 'center' }}>
            <Icon name={ic} size={17} color={C.good} stroke={2.4} />
          </div>
          <div style={{ fontFamily: SANS, fontSize: 18.5, fontWeight: 600, color: C.fg }}>{label}</div>
        </div>
      ))}

      {/* Formulaire rempli à la main */}
      <Card style={abs(620, 160, { width: 580, height: 452, padding: '26px 28px', ...enter(t, 22.2, 0.7, { x: 520, r: 4, blur: 14 }) })}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div style={{ fontFamily: SANS, fontWeight: 800, fontSize: 22, color: C.fg }}>Nouveau devis</div>
          <div style={{ fontFamily: MONO, fontSize: 14, color: C.muted }}>D-2026-043</div>
        </div>
        <div style={{ marginTop: 24 }}>
          <Field label="Client" w={524} active={t >= 22.95 && t < 23.4} value={typed('Atelier Dupont', t, 23.0, 34)} />
        </div>
        <div style={{ marginTop: 14 }}>
          <Field label="Désignation" w={524} active={t >= 23.4 && t < 24.1} value={typed('Pose de cloison placo', t, 23.5, 32)} />
        </div>
        <div style={{ marginTop: 14, display: 'flex', gap: 18 }}>
          <Field label="Quantité (m²)" w={120} active={t >= 24.1 && t < 24.45} value={t >= 24.18 ? '12' : ''} />
          <Field label="Prix unitaire" w={160} active={t >= 24.45 && t < 24.85} value={typed('35,00 €', t, 24.5, 26)} />
          <Field label="Total HT" w={210} computed flash={t >= 24.85 && t < 25.6} value={totalOn ? euro(420) : '—'} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 34 }}>
          <div style={{ fontFamily: SANS, fontSize: 14, color: C.good, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, ...appear(t, 24.9, 0.35, 6) }}>
            <Icon name="check" size={16} color={C.good} stroke={3} /> Calculé par le serveur
          </div>
          <div style={{ padding: '13px 20px', borderRadius: 12, background: C.accent, color: '#fff', fontFamily: SANS, fontWeight: 700, fontSize: 16.5,
            transform: `scale(${pressed ? 0.92 : 1})`, boxShadow: '0 8px 20px -8px rgba(232,81,14,.7)' }}>
            Créer le devis
          </div>
        </div>
        <div style={abs(178, 386, { padding: '10px 16px', borderRadius: 12, background: C.dark, color: C.darkFg, fontFamily: SANS, fontWeight: 600,
          fontSize: 15, display: 'flex', alignItems: 'center', gap: 8, ...pop(t, 25.35, 0.4) })}>
          <Icon name="check" size={17} color="#4ade80" stroke={3} /> Devis D-2026-043 créé
        </div>
      </Card>

      {/* Clics */}
      {clicks.map((ct, i) => {
        const k = prog(t, ct, 0.45)
        if (k <= 0 || k >= 1) return null
        const [x, y] = [CURSOR[i + 1][1], CURSOR[i + 1][2]]
        return <div key={i} style={abs(x - 22 * k * 1.4, y - 22 * k * 1.4, { width: 44 * k * 1.4, height: 44 * k * 1.4, borderRadius: '50%',
          border: `3px solid ${C.accent}`, opacity: 1 - k })} />
      })}
      {t >= 22.5 && (
        <svg width="30" height="34" viewBox="0 0 24 28" style={abs(cx - 4, cy - 2, { filter: 'drop-shadow(0 3px 4px rgba(0,0,0,.3))' })}>
          <path d="M3 2l17 11-7.5 1.5L17 23l-3.5 1.8-4.4-8.7L3 21z" fill={C.fg} stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
        </svg>
      )}
    </Layer>
  )
}

/* ─── Scène 6 : 100 % libre (26 – 31 s) ────────────────────────────── */
// Arrivée en panoramique éclair ; à la fin, la pastille AGPL grandit jusqu'à devenir le fond de l'outro.
const MODULES = ['Accueil', 'Ventes', 'Achats', 'CRM', 'Production', 'Logistique', 'Données tech.', 'RH', 'Projets', 'Qualité', 'Maintenance', 'Comptabilité', 'Paramètres']
const LIT = [1, 3, 4, 7, 11, 5]
const GROW_AT = 30.62
const PILL_RECT = [80, 258, 174, 36]

function OpenSource({ t }) {
  const l1 = '$ git clone https://github.com/moreauremi/caffein'
  const l3 = '$ docker compose up -d'
  const grow = eInOutExpo(prog(t, GROW_AT, 0.6))
  const pill = lerpRect(PILL_RECT, [0, 0, W, H], grow)
  const growing = t >= GROW_AT
  return (
    <Layer style={enter(t, WHIP_AT + 0.2, 0.6, { x: 1500, blur: 22 })}>
      <Layer style={leave(t, GROW_AT - 0.02, 0.45, { s: 0.9, blur: 10 })}>
        <Kicker style={abs(80, 76)}><Kinetic t={t} start={25.9} parts={[['Open source']]} /></Kicker>
        <div style={abs(78, 102, { fontFamily: SERIF, fontSize: 76, lineHeight: 1, color: C.fg })}>
          <Kinetic t={t} start={25.95} parts={[['100 %'], ['libre.', { color: C.accent, fontStyle: 'italic' }]]} stagger={0.09} dur={0.8} />
        </div>
        <div style={abs(80, 190, { width: 560, fontFamily: SANS, fontSize: 21, lineHeight: 1.4, color: C.muted, ...enter(t, 26.15, 0.6, { y: 20, blur: 6 }) })}>
          Le code est à vous : lisez-le, modifiez-le, hébergez-le chez vous.
        </div>
        <div style={abs(80, 258, { display: 'flex', gap: 10 })}>
          {['Licence AGPL-3.0', 'FastAPI', 'React', 'Docker'].map((b, i) => (
            <div key={b} style={{ padding: '8px 14px', borderRadius: 999, fontFamily: SANS, fontWeight: 700, fontSize: 15, whiteSpace: 'nowrap',
              background: i === 0 ? C.accent : C.surface, color: i === 0 ? '#fff' : C.fg, border: `1px solid ${i === 0 ? C.accent : C.border}`,
              display: 'flex', alignItems: 'center', gap: 7, opacity: i === 0 && growing ? 0 : undefined, ...pop(t, 26.25 + i * 0.08, 0.4) }}>
              {i === 0 && <Icon name="scale" size={16} color="#fff" />}{b}
            </div>
          ))}
        </div>

        {/* Terminal */}
        <div style={abs(80, 330, { width: 580, height: 270, borderRadius: 16, background: C.dark, boxShadow: '0 30px 60px -25px rgba(0,0,0,.55)',
          overflow: 'hidden', ...enter(t, 26.0, 0.7, { y: 120, r: -3, blur: 12 }) })}>
          <div style={{ height: 40, display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', borderBottom: '1px solid #2a2a27' }}>
            {['#ff5f57', '#febc2e', '#28c840'].map((c) => <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c }} />)}
            <div style={{ flex: 1, textAlign: 'center', fontFamily: MONO, fontSize: 13, color: '#8a8a84', marginRight: 52 }}>~/caffein</div>
          </div>
          <div style={{ padding: '18px 20px', fontFamily: MONO, fontSize: 15.5, lineHeight: 1.85, color: C.darkFg }}>
            <div style={{ whiteSpace: 'nowrap' }}>{typed(l1, t, 26.7, 48)}</div>
            {t >= 27.85 && <div style={{ color: '#8a8a84' }}>Clonage dans « caffein »… fait.</div>}
            {t >= 28.05 && <div>{typed(l3, t, 28.05, 32)}</div>}
            {t >= 28.9 && <div><span style={{ color: '#4ade80' }}>✔</span> Container caffein <span style={{ color: '#4ade80' }}>Started</span></div>}
            {t >= 29.2 && <div style={{ color: '#FF8A55' }}>→ http://localhost:8000 <span style={{ display: 'inline-block', width: 9, height: 18, background: C.darkFg, verticalAlign: 'middle', opacity: Math.sin(t * 9) > 0 ? 1 : 0 }} /></div>}
          </div>
        </div>

        {/* Modules */}
        <div style={abs(704, 92, { fontFamily: SANS, fontWeight: 700, fontSize: 18, color: C.fg, ...enter(t, 26.1, 0.6, { y: 16, blur: 6 }) })}>
          13 modules. <span style={{ color: C.muted, fontWeight: 500 }}>Activez seulement ce qu'il vous faut.</span>
        </div>
        <div style={abs(704, 134, { display: 'grid', gridTemplateColumns: 'repeat(3, 166px)', gap: 11 })}>
          {MODULES.map((m, i) => {
            const litAt = LIT.indexOf(i)
            const on = litAt >= 0 && t >= 29.0 + litAt * 0.12
            const lit = litAt >= 0 ? punch(t, 29.0 + litAt * 0.12, 0.08) : 0
            return (
              <div key={m} style={{ height: 58, borderRadius: 14, padding: '0 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: on ? C.accentSoft : C.surface, border: `1.5px solid ${on ? C.accent : C.border}`, boxShadow: '0 1px 2px rgba(0,0,0,.04)',
                fontFamily: SANS, fontWeight: 600, fontSize: 15, whiteSpace: 'nowrap', gap: 8, color: on ? C.accentInk : C.fg,
                ...(t < 26.25 + i * 0.06 + 0.6 ? enter(t, 26.25 + i * 0.06, 0.6, { y: 60, s: 0.7, blur: 10 }) : { transform: `scale(${1 + lit})` }) }}>
                {m}
                <div style={{ width: 26, height: 15, borderRadius: 8, background: on ? C.accent : C.surface3, position: 'relative', flexShrink: 0 }}>
                  <div style={{ position: 'absolute', top: 2, left: on ? 13 : 2, width: 11, height: 11, borderRadius: 6, background: '#fff' }} />
                </div>
              </div>
            )
          })}
        </div>
        <div style={abs(704, 520, { fontFamily: SERIF, fontSize: 36, lineHeight: 1.2, color: C.fg, width: 490 })}>
          <Kinetic t={t} start={29.55} parts={[['Votre serveur. Vos données.'], ['\n'], ['Votre code.', { color: C.accent, fontStyle: 'italic' }]]} stagger={0.07} />
        </div>
      </Layer>
      {growing && (
        <div style={abs(pill[0], pill[1], { width: pill[2], height: pill[3], borderRadius: lerp(18, 0, grow), background: C.accent,
          display: 'flex', alignItems: 'center', gap: 7, padding: '0 14px', overflow: 'hidden' })}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, opacity: 1 - prog(t, GROW_AT, 0.12), whiteSpace: 'nowrap',
            fontFamily: SANS, fontWeight: 700, fontSize: 15, color: '#fff' }}>
            <Icon name="scale" size={16} color="#fff" />Licence AGPL-3.0
          </div>
        </div>
      )}
    </Layer>
  )
}

/* ─── Scène 7 : outro (31 – 35 s) ──────────────────────────────────── */
const BURST = Array.from({ length: 22 }, (_, i) => ({ a: (i / 22) * Math.PI * 2 + (i % 3) * 0.2, d: 170 + (i * 37) % 140, s: 8 + (i % 4) * 4, dark: i % 3 === 0 }))

function Outro({ t }) {
  const burst = prog(t, 31.7, 1.1)
  const shine = prog(t, 33.7, 0.8)
  const wordW = 720
  const left = (W - wordW) / 2
  return (
    <Layer>
      {burst > 0 && burst < 1 && BURST.map((b, i) => (
        <div key={i} style={abs(640 + Math.cos(b.a) * b.d * 1.6 * eOutExpo(burst) - b.s / 2, 245 + Math.sin(b.a) * b.d * eOutExpo(burst) - b.s / 2, {
          width: b.s, height: b.s, borderRadius: i % 2 ? b.s : 3, background: b.dark ? C.dark : '#fff', opacity: 1 - burst,
          transform: `rotate(${burst * 360}deg)` })} />
      ))}
      <Steam t={t} start={32.1} x={left + (LOGO_LETTERS[4][1] / LOGO_W) * wordW} y={160} color="#fff" />
      <div style={abs(left, 180)}>
        <Wordmark t={t} start={31.32} width={wordW} color="#fff" step={0.07} />
      </div>
      <div style={abs(0, 358, { width: W, textAlign: 'center', fontFamily: SERIF, fontSize: 48, color: '#fff' })}>
        <Kinetic t={t} start={32.1} parts={[['Libre.'], ['Auto-hébergé.'], ['Avec ou sans IA.', { fontStyle: 'italic' }]]} stagger={0.12} dur={0.8} />
      </div>
      <div style={abs(0, 462, { width: W, display: 'flex', justifyContent: 'center' })}>
        <div style={{ position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', gap: 12, padding: '15px 26px', borderRadius: 999,
          background: '#fff', color: C.fg, fontFamily: MONO, fontWeight: 600, fontSize: 21, boxShadow: '0 20px 40px -18px rgba(0,0,0,.45)',
          ...enter(t, 33.1, 0.7, { y: 50, s: 0.6, blur: 10 }) }}>
          <Icon name="github" size={24} color={C.fg} />
          github.com/<span style={{ color: C.accent }}>moreauremi/caffein</span>
          {shine > 0 && shine < 1 && (
            <div style={abs(lerp(-120, 520, shine), -10, { width: 60, height: 80, background: 'linear-gradient(90deg, transparent, rgba(232,81,14,.18), transparent)',
              transform: 'skewX(-20deg)' })} />
          )}
        </div>
      </div>
      <div style={abs(0, 556, { width: W, textAlign: 'center', fontFamily: SANS, fontWeight: 600, fontSize: 17, color: 'rgba(255,255,255,.88)',
        letterSpacing: '.02em', ...enter(t, 33.7, 0.6, { y: 16, blur: 6 }) })}>
        AGPL-3.0 · docker compose up -d · Français / English
      </div>
    </Layer>
  )
}

/* ─── La scène complète ────────────────────────────────────────────── */
function Stage({ t }) {
  return (
    <>
      <Background t={t} />
      <Scene t={t} from={0} to={4.12} drift={0.04} punches={[0.98]}><Intro t={t} /></Scene>
      <Scene t={t} from={4.05} to={9.25} punches={[7.6]}><Chores t={t} /></Scene>
      <Scene t={t} from={8.4} to={15.26} drift={0.025} punches={[11.92, 13.97]}><QuoteFromSentence t={t} /></Scene>
      <Scene t={t} from={14.9} to={21.06} drift={0.02} punches={[17.85]}><Delegated t={t} /></Scene>
      <Scene t={t} from={21.0} to={26.2} drift={0.02} punches={[FLIP_AT + 0.1, 25.22]} origin="640px 360px"><WithoutAI t={t} /></Scene>
      <Scene t={t} from={25.9} to={31.3} drift={0.02} punches={[29.0]}><OpenSource t={t} /></Scene>
      <Scene t={t} from={OUTRO_AT} to={DURATION + 1} drift={0.05} punches={[31.75]}><Outro t={t} /></Scene>
      <Blackout t={t} />
    </>
  )
}

/* ─── Export MP4 ───────────────────────────────────────────────────── */
// Chaque image est rendue par React au temps voulu, sérialisée en SVG (foreignObject), dessinée sur un canvas
// 1920 × 1080, encodée par WebCodecs, puis rangée dans un fichier MP4 écrit ci-dessous (aucune bibliothèque).

const EXPORT_FPS = 30
const EXPORT_W = 1920
const EXPORT_H = 1080
const FONT_CSS_URL =
  'https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400..800&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;600&display=swap'
const CODECS = [
  { codec: 'avc1.640028', label: 'H.264' }, // High, niveau 4.0 (1080p)
  { codec: 'avc1.4d0028', label: 'H.264' }, // Main
  { codec: 'avc1.42e028', label: 'H.264' }, // Baseline
  { codec: 'vp09.00.40.08', label: 'VP9' }, // secours sans H.264
]

// Une image dessinée dans un SVG n'a pas accès aux polices de la page : on les embarque (sous-ensemble latin).
let fontCssPromise = null
function embeddedFontCss() {
  if (!fontCssPromise) {
    fontCssPromise = (async () => {
      try {
        const css = await (await fetch(FONT_CSS_URL)).text()
        const blocks = css.split('/* ').filter((b) => b.startsWith('latin */')).map((b) => b.slice('latin */'.length))
        const out = []
        for (const block of blocks) {
          const url = block.match(/url\(([^)]+)\)/)?.[1]
          if (!url) continue
          const blob = await (await fetch(url)).blob()
          const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => resolve(reader.result)
            reader.onerror = reject
            reader.readAsDataURL(blob)
          })
          out.push(block.replace(url, dataUrl))
        }
        return out.join('\n')
      } catch {
        return '' // hors ligne : polices de secours du système
      }
    })()
  }
  return fontCssPromise
}

function frameSvg(stage, fontCss) {
  const clone = stage.cloneNode(true)
  clone.style.transform = 'none'
  const xhtml = new XMLSerializer().serializeToString(clone)
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${EXPORT_W}" height="${EXPORT_H}" viewBox="0 0 ${W} ${H}">`
    + `<foreignObject x="0" y="0" width="${W}" height="${H}">`
    + `<style xmlns="http://www.w3.org/1999/xhtml">${fontCss} *{box-sizing:border-box}</style>${xhtml}</foreignObject></svg>`
}

async function drawSvg(ctx, svg) {
  const img = new Image()
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
  await img.decode()
  ctx.clearRect(0, 0, EXPORT_W, EXPORT_H)
  ctx.drawImage(img, 0, 0, EXPORT_W, EXPORT_H)
}

async function pickCodec() {
  if (typeof VideoEncoder === 'undefined') return null
  for (const c of CODECS) {
    const config = {
      codec: c.codec, width: EXPORT_W, height: EXPORT_H, bitrate: 10_000_000, framerate: EXPORT_FPS, latencyMode: 'quality',
      ...(c.codec.startsWith('avc1') ? { avc: { format: 'avc' } } : {}),
    }
    try {
      if ((await VideoEncoder.isConfigSupported(config)).supported) return { ...c, config }
    } catch {
      /* codec suivant */
    }
  }
  return null
}

/* Écriture MP4 (ISO BMFF) : une piste vidéo, échantillons à intervalle fixe, « moov » en tête (lecture immédiate). */
const u8 = (...parts) => {
  const flat = parts.flat(Infinity)
  const len = flat.reduce((n, p) => n + (p instanceof Uint8Array ? p.length : 1), 0)
  const out = new Uint8Array(len)
  let o = 0
  for (const p of flat) {
    if (p instanceof Uint8Array) {
      out.set(p, o)
      o += p.length
    } else out[o++] = p
  }
  return out
}
const u16 = (n) => [(n >>> 8) & 255, n & 255]
const u32 = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]
const ascii = (s) => [...s].map((ch) => ch.charCodeAt(0))
const box = (type, ...body) => {
  const content = u8(...body)
  return u8(u32(content.length + 8), ascii(type), content)
}
const fullBox = (type, version, flags, ...body) => box(type, [version, (flags >>> 16) & 255, (flags >>> 8) & 255, flags & 255], ...body)
const MATRIX = [0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000].map(u32)

export function muxMp4({ codec, width, height, fps, description, samples }) {
  const timescale = fps * 1000
  const n = samples.length
  const durationMs = Math.round((n / fps) * 1000)
  let configBox
  let fourcc
  if (codec.startsWith('avc1')) {
    fourcc = 'avc1'
    configBox = box('avcC', description)
  } else if (codec.startsWith('vp09')) {
    fourcc = 'vp09'
    const [, profile, level, depth] = codec.split('.').map(Number)
    // vpcC : profil, niveau, profondeur, sous-échantillonnage 4:2:0, BT.709, plage limitée
    configBox = fullBox('vpcC', 1, 0, [profile, level, (depth << 4) | (1 << 1)], [1, 1, 1], u16(0))
  } else throw new Error(`Codec non géré : ${codec}`)
  const colr = box('colr', ascii('nclx'), u16(1), u16(1), u16(1), [0])
  const entry = box(fourcc, [0, 0, 0, 0, 0, 0], u16(1), u16(0), u16(0), u32(0), u32(0), u32(0), u16(width), u16(height),
    u32(0x00480000), u32(0x00480000), u32(0), u16(1), new Array(32).fill(0), u16(0x18), u16(0xffff), configBox, colr)
  const keys = samples.map((s, i) => (s.key ? i + 1 : 0)).filter(Boolean)
  const moov = (offset) => box('moov',
    fullBox('mvhd', 0, 0, u32(0), u32(0), u32(1000), u32(durationMs), u32(0x00010000), u16(0x0100), u16(0), u32(0), u32(0),
      MATRIX, [0, 0, 0, 0, 0, 0].map(u32), u32(2)),
    box('trak',
      fullBox('tkhd', 0, 3, u32(0), u32(0), u32(1), u32(0), u32(durationMs), u32(0), u32(0), u16(0), u16(0), u16(0), u16(0),
        MATRIX, u32(width * 65536), u32(height * 65536)),
      box('mdia',
        fullBox('mdhd', 0, 0, u32(0), u32(0), u32(timescale), u32(n * 1000), u16(0x55c4), u16(0)),
        fullBox('hdlr', 0, 0, u32(0), ascii('vide'), u32(0), u32(0), u32(0), ascii('Caffein'), [0]),
        box('minf',
          fullBox('vmhd', 0, 1, u16(0), u16(0), u16(0), u16(0)),
          box('dinf', fullBox('dref', 0, 0, u32(1), fullBox('url ', 0, 1))),
          box('stbl',
            fullBox('stsd', 0, 0, u32(1), entry),
            fullBox('stts', 0, 0, u32(1), u32(n), u32(1000)),
            fullBox('stss', 0, 0, u32(keys.length), keys.map(u32)),
            fullBox('stsc', 0, 0, u32(1), u32(1), u32(n), u32(1)),
            fullBox('stsz', 0, 0, u32(0), u32(n), samples.map((s) => u32(s.data.length))),
            fullBox('stco', 0, 0, u32(1), u32(offset)))))))
  const ftyp = box('ftyp', ascii('isom'), u32(0x200), ascii('isom'), ascii('iso2'), ascii(fourcc === 'avc1' ? 'avc1' : 'iso6'), ascii('mp41'))
  const dataLength = samples.reduce((s, x) => s + x.data.length, 0)
  const head = moov(ftyp.length + moov(0).length + 8)
  return new Blob([ftyp, head, new Uint8Array([...u32(dataLength + 8), ...ascii('mdat')]), ...samples.map((s) => s.data)], { type: 'video/mp4' })
}

/* ─── Contrôles ────────────────────────────────────────────────────── */
function Controls({ t, playing, onToggle, onRestart, onSeek, onExport, exporting, notice }) {
  const barRef = useRef(null)
  const seekFrom = (e) => {
    if (exporting) return
    const r = barRef.current.getBoundingClientRect()
    onSeek(clamp((e.clientX - r.left) / r.width) * DURATION)
  }
  const btn = { width: 38, height: 38, borderRadius: 19, border: `1px solid ${C.border}`, background: C.surface, cursor: 'pointer',
    display: 'grid', placeItems: 'center', color: C.fg, flexShrink: 0, opacity: exporting ? 0.4 : 1 }
  return (
    <div style={{ marginTop: 12, fontFamily: SANS }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button type="button" onClick={onToggle} disabled={exporting} style={btn} aria-label={playing ? 'Pause' : 'Lecture'}>
          <svg width="16" height="16" viewBox="0 0 16 16">
            {playing ? <path d="M4 2h3v12H4zM9 2h3v12H9z" fill="currentColor" /> : <path d="M4 2l10 6-10 6z" fill="currentColor" />}
          </svg>
        </button>
        <button type="button" onClick={onRestart} disabled={exporting} style={btn} aria-label="Rejouer">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8 M3 3v5h5" />
          </svg>
        </button>
        <div ref={barRef} onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seekFrom(e) }}
          onPointerMove={(e) => { if (e.buttons) seekFrom(e) }}
          style={{ flex: 1, height: 22, display: 'flex', alignItems: 'center', cursor: exporting ? 'default' : 'pointer', touchAction: 'none' }}>
          <div style={{ position: 'relative', width: '100%', height: 6, borderRadius: 3, background: C.surface3 }}>
            {BEATS.map((c) => <div key={c} style={{ position: 'absolute', left: `${(c / DURATION) * 100}%`, top: 0, width: 2, height: 6, background: '#fff' }} />)}
            <div style={{ position: 'absolute', left: 0, top: 0, height: 6, borderRadius: 3, width: `${(t / DURATION) * 100}%`, background: C.accent }} />
          </div>
        </div>
        <div style={{ fontSize: 13, color: C.muted, fontVariantNumeric: 'tabular-nums', minWidth: 76, textAlign: 'right' }}>
          {t.toFixed(1).replace('.', ',')} / {DURATION} s
        </div>
        <button type="button" onClick={onExport} disabled={exporting}
          style={{ height: 38, padding: '0 16px', borderRadius: 19, border: 'none', background: C.accent, color: '#fff', cursor: exporting ? 'default' : 'pointer',
            fontFamily: SANS, fontWeight: 700, fontSize: 14, display: 'flex', alignItems: 'center', gap: 7, flexShrink: 0, opacity: exporting ? 0.6 : 1 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v12 M7 10l5 5 5-5 M5 21h14" />
          </svg>
          {exporting ? 'Export…' : 'MP4'}
        </button>
      </div>
      {notice && (
        <div style={{ marginTop: 10, fontSize: 13.5, lineHeight: 1.45, color: notice.kind === 'error' ? C.bad : C.muted }}>{notice.text}</div>
      )}
    </div>
  )
}

function ExportOverlay({ progress, onCancel }) {
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(22,22,20,.55)', display: 'grid', placeItems: 'center', fontFamily: SANS, zIndex: 2 }}>
      <div style={{ background: C.surface, borderRadius: 16, padding: '20px 24px', width: 'min(360px, 80%)', boxShadow: SHADOW }}>
        <div style={{ fontWeight: 700, fontSize: 16, color: C.fg }}>Export MP4 en cours… {Math.floor(progress * 100)} %</div>
        <div style={{ fontSize: 13, color: C.muted, marginTop: 4 }}>1920 × 1080, 30 images/s. Garde cet onglet ouvert.</div>
        <div style={{ height: 6, borderRadius: 3, background: C.surface3, marginTop: 14, overflow: 'hidden' }}>
          <div style={{ height: 6, width: `${progress * 100}%`, background: C.accent }} />
        </div>
        <button type="button" onClick={onCancel} style={{ marginTop: 14, height: 34, padding: '0 14px', borderRadius: 10, border: `1px solid ${C.border}`,
          background: C.surface, color: C.fg, fontFamily: SANS, fontWeight: 600, fontSize: 13.5, cursor: 'pointer' }}>
          Annuler
        </button>
      </div>
    </div>
  )
}

/* ─── Composant principal ──────────────────────────────────────────── */
export default function CaffeinPromo({ autoPlay = true, loop = false, showControls = true, time }) {
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(autoPlay)
  const [scale, setScale] = useState(1)
  const [exportT, setExportT] = useState(null)
  const [progress, setProgress] = useState(0)
  const [notice, setNotice] = useState(null)
  const tRef = useRef(0)
  const boxRef = useRef(null)
  const stageRef = useRef(null)
  const cancelRef = useRef(false)
  const controlled = typeof time === 'number'
  const exporting = exportT !== null

  useEffect(() => {
    const el = boxRef.current
    if (!el) return undefined
    const ro = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / W))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!playing || controlled || exporting) return undefined
    let raf
    let last
    const tick = (now) => {
      const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000)
      last = now
      let n = tRef.current + dt
      if (n >= DURATION) {
        if (loop) n -= DURATION
        else {
          tRef.current = DURATION
          setT(DURATION)
          setPlaying(false)
          return
        }
      }
      tRef.current = n
      setT(n)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, loop, controlled, exporting])

  const seek = (v) => {
    tRef.current = v
    setT(v)
  }
  const toggle = () => {
    if (exporting) return
    if (!playing && tRef.current >= DURATION) seek(0)
    setPlaying((p) => !p)
  }

  const exportMp4 = async () => {
    if (exporting) return
    setNotice(null)
    const picked = await pickCodec()
    if (!picked) {
      setNotice({ kind: 'error', text: "Ce navigateur ne sait pas encoder de vidéo (WebCodecs). Ouvre l'animation dans Chrome ou Edge récent." })
      return
    }
    setPlaying(false)
    cancelRef.current = false
    flushSync(() => { setExportT(0); setProgress(0) })
    const total = Math.round(DURATION * EXPORT_FPS)
    const samples = []
    let description = null
    let encodeError = null
    const encoder = new VideoEncoder({
      output: (chunk, meta) => {
        const desc = meta?.decoderConfig?.description
        if (desc && !description) {
          description = ArrayBuffer.isView(desc) ? new Uint8Array(desc.buffer, desc.byteOffset, desc.byteLength).slice() : new Uint8Array(desc).slice()
        }
        const data = new Uint8Array(chunk.byteLength)
        chunk.copyTo(data)
        samples.push({ data, key: chunk.type === 'key' })
      },
      error: (e) => { encodeError = e },
    })
    try {
      encoder.configure(picked.config)
      const fontCss = await embeddedFontCss()
      const canvas = document.createElement('canvas')
      canvas.width = EXPORT_W
      canvas.height = EXPORT_H
      const ctx = canvas.getContext('2d')
      for (let i = 0; i < total; i++) {
        if (cancelRef.current) throw new Error('cancelled')
        if (encodeError) throw encodeError
        flushSync(() => setExportT(i / EXPORT_FPS))
        await drawSvg(ctx, frameSvg(stageRef.current, fontCss))
        const frame = new VideoFrame(canvas, { timestamp: Math.round((i * 1e6) / EXPORT_FPS), duration: Math.round(1e6 / EXPORT_FPS) })
        encoder.encode(frame, { keyFrame: i % (EXPORT_FPS * 2) === 0 })
        frame.close()
        while (encoder.encodeQueueSize > 4) await new Promise((r) => setTimeout(r, 4))
        if (i % 3 === 0) setProgress(i / total)
      }
      await encoder.flush()
      if (picked.codec.startsWith('avc1') && !description) throw new Error("l'encodeur n'a pas fourni sa configuration H.264")
      const blob = muxMp4({ codec: picked.codec, width: EXPORT_W, height: EXPORT_H, fps: EXPORT_FPS, description, samples })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'caffein-presentation.mp4'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setNotice({
        kind: 'ok',
        text: `caffein-presentation.mp4 téléchargé (${(blob.size / 1e6).toFixed(1).replace('.', ',')} Mo, ${picked.label}, 1920 × 1080).`
          + (picked.label === 'VP9' ? " Ton navigateur n'a pas H.264 : la vidéo se lit dans Chrome, Firefox et VLC, pas dans QuickTime. Pour du H.264, exporte depuis Chrome ou Edge." : ''),
      })
    } catch (e) {
      if (e?.message !== 'cancelled') {
        const tainted = e?.name === 'SecurityError'
        setNotice({ kind: 'error', text: tainted
          ? "Ce navigateur bloque la capture des images (Safari ?). Ouvre l'animation dans Chrome ou Edge."
          : `L'export a échoué : ${e?.message ?? e}` })
      }
    } finally {
      if (encoder.state !== 'closed') encoder.close()
      setExportT(null)
      setProgress(0)
    }
  }

  const T = controlled ? clamp(time, 0, DURATION) : exporting ? exportT : t

  return (
    <div className="caffein-promo" style={{ width: '100%' }}
      tabIndex={-1}
      onKeyDown={(e) => { if (e.code === 'Space') { e.preventDefault(); toggle() } }}>
      <style>{"@import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400..800&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;600&display=swap'); .caffein-promo, .caffein-promo * { box-sizing: border-box; }"}</style>
      <div ref={boxRef} style={{ position: 'relative', width: '100%', aspectRatio: '16 / 9', overflow: 'hidden', borderRadius: 16, background: C.bg }}>
        <div ref={stageRef} style={{ position: 'absolute', left: 0, top: 0, width: W, height: H, overflow: 'hidden', transform: `scale(${scale})`, transformOrigin: '0 0' }}>
          <Stage t={T} />
        </div>
        {exporting && <ExportOverlay progress={progress} onCancel={() => { cancelRef.current = true }} />}
      </div>
      {showControls && !controlled && (
        <Controls t={T} playing={playing} onToggle={toggle} onRestart={() => { seek(0); setPlaying(true) }} onSeek={seek}
          onExport={exportMp4} exporting={exporting} notice={notice} />
      )}
    </div>
  )
}
