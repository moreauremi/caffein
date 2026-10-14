// SPDX-License-Identifier: AGPL-3.0-or-later
// « Caffein · Mes vues » : vidéo de démonstration (Remotion).
// L'interface reproduit la vraie page /vues (mêmes couleurs, polices, icônes et textes) ; les chiffres
// viennent de data.json, c'est-à-dire des réponses réelles de l'instance de démonstration.
import { useEffect, useState } from 'react'
import {
  AbsoluteFill, Easing, Series, continueRender, delayRender, interpolate, spring, useCurrentFrame, useVideoConfig,
} from 'remotion'
import {
  AlertTriangle, ArrowRight, Bot, Braces, Check, CheckCircle2, Cpu, EyeOff, FileStack, Home, Landmark,
  LayoutDashboard, LayoutGrid, MessageSquareText, Moon, Percent, ReceiptText, Save, Server, ShieldCheck, Sparkles,
  Table2, Trash2, Wallet, WandSparkles, X,
} from 'lucide-react'
import data from './data.json'

// ── Durées (images, 30 par seconde) ───────────────────────────────────
export const FPS = 30
const D = { title: 120, demo: 1060, explain: 285, roadmap: 165, end: 95 }
export const DURATION = Object.values(D).reduce((a, b) => a + b, 0)

// ── Outils ────────────────────────────────────────────────────────────
const NB = ' ' // espace insécable (avant « : »)
const NNB = ' ' // espace fine insécable (avant « ; ! ? », dans « »)
const EASE = Easing.bezier(0.2, 0.8, 0.2, 1)
const CLAMP = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
const ramp = (f, a, b, from = 0, to = 1, easing = EASE) => interpolate(f, [a, b], [from, to], { ...CLAMP, easing })
const lerp = (a, b, p) => a + (b - a) * p
const typed = (f, start, text, fpc) => text.slice(0, Math.max(0, Math.min(text.length, Math.floor((f - start) / fpc))))

const money = (v) => new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(v)
const compactMoney = (v) => (Math.abs(v) < 1000
  ? `${Math.round(v)} €`
  : `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(v / 1000)} k€`)
const frDate = (iso) => iso.split('-').reverse().join('/')

// ── Styles : extraits de frontend/src/index.css (thème clair) ─────────
const CSS = `
:root, .app {
  --bg: #FAFAF8; --fg: #1A1A18; --surface: #FFFFFF; --surface-2: #F4F4F1; --surface-3: #ECECE8;
  --border: #E8E8E4; --border-strong: #D6D6D0; --accent: #E8510E; --accent-soft: rgba(232, 81, 14, 0.09);
  --accent-ink: #B83E07; --muted: #6B6B66; --subtle: #96968F;
  --good: #15803d; --good-soft: rgba(21, 128, 61, 0.1); --warn: #b45309; --warn-soft: rgba(217, 119, 6, 0.12);
  --bad: #dc2626; --bad-soft: rgba(220, 38, 38, 0.09); --info: #2563eb; --info-soft: rgba(37, 99, 235, 0.09);
  --series-collected: #2a78d6; --series-deductible: #E8510E; --grid: #EDEDE9;
  --radius-lg: 18px;
  --shadow-sm: 0 1px 2px rgba(20, 20, 18, 0.04);
  --shadow: 0 1px 2px rgba(20, 20, 18, 0.04), 0 8px 24px -12px rgba(20, 20, 18, 0.12);
  --shadow-lg: 0 24px 60px -20px rgba(20, 20, 18, 0.35);
  --font: 'DM Sans Variable', 'DM Sans', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}
.app { font-family: var(--font); color: var(--fg); background: var(--bg); font-size: 15px; line-height: 1.5;
  -webkit-font-smoothing: antialiased; }
.app *, .app *::before, .app *::after { box-sizing: border-box; }
.app h1, .app h2 { margin: 0; line-height: 1.2; letter-spacing: -0.015em; font-weight: 650; }
.app p { margin: 0; }
.app svg { display: block; }
.mono { font-family: var(--font-mono); font-feature-settings: 'tnum' 1; letter-spacing: -0.01em; }
.muted { color: var(--muted); } .small { font-size: 13px; } .xsmall { font-size: 12px; } .right { text-align: right; }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.row { display: flex; align-items: center; gap: 10px; } .between { justify-content: space-between; } .grow { flex: 1; min-width: 0; }
.container { width: 100%; max-width: 1200px; margin: 0 auto; padding: 0 24px; }
.page { padding: 32px 0 72px; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 28px; }
.page-title { font-size: 30px; font-weight: 650; letter-spacing: -0.025em; }
.page-sub { color: var(--muted); margin-top: 6px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow); padding: 20px; min-width: 0; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 650; margin: 0; }
.stat { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.stat-label { font-size: 13px; color: var(--muted); display: flex; align-items: center; gap: 8px; }
.stat-icon { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-2); color: var(--fg); }
.stat-value { font-family: var(--font-mono); font-size: 26px; font-weight: 500; letter-spacing: -0.03em; line-height: 1.1; }
.stat-foot { font-size: 12.5px; color: var(--muted); }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; height: 38px; padding: 0 15px; border-radius: 10px;
  border: 1px solid var(--border-strong); background: var(--surface); color: var(--fg); font-weight: 550; font-size: 14px; white-space: nowrap; font-family: var(--font); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; box-shadow: 0 1px 0 rgba(255,255,255,0.15) inset, 0 6px 16px -8px rgba(232, 81, 14, 0.7); }
.btn.ghost { background: transparent; border-color: transparent; }
.btn.danger { color: var(--bad); border-color: transparent; background: transparent; }
.btn.sm { height: 32px; padding: 0 11px; font-size: 13px; border-radius: 8px; gap: 6px; }
.icon-btn { width: 34px; height: 34px; display: inline-grid; place-items: center; border-radius: 9px; color: var(--muted); }
.badge { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 12px; font-weight: 600;
  white-space: nowrap; background: var(--surface-2); color: var(--muted); border: 1px solid transparent; }
.badge.bad { background: var(--bad-soft); color: var(--bad); }
.badge.outline { background: transparent; border-color: var(--border-strong); color: var(--muted); }
.key { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.legend { display: flex; gap: 16px; font-size: 13px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { height: 30px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--muted);
  font-size: 13px; font-weight: 550; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.chip.active { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.input { height: 34px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--accent); background: var(--surface);
  box-shadow: 0 0 0 3px var(--accent-soft); font-size: 13.5px; display: flex; align-items: center; }
.table { width: 100%; border-collapse: collapse; font-size: 14px; }
.table th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--subtle); font-weight: 650;
  padding: 11px 14px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.table td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.table tr:last-child td { border-bottom: 0; }
.table .right { text-align: right; }
.alert { display: flex; gap: 12px; align-items: flex-start; padding: 13px 15px; border-radius: 12px; font-size: 14px; border: 1px solid; }
.alert svg { flex: none; margin-top: 1px; }
.alert.info { background: var(--info-soft); border-color: rgba(37, 99, 235, 0.2); }
.alert.info svg { color: var(--info); }
.alert.warn { background: var(--warn-soft); border-color: rgba(180, 83, 9, 0.25); }
.alert.warn svg { color: var(--warn); }
.navbar { position: absolute; top: 0; left: 0; right: 0; z-index: 40; background: rgba(250, 250, 248, 0.86);
  backdrop-filter: blur(14px) saturate(1.4); border-bottom: 1px solid var(--border); }
.navbar-inner { height: 62px; display: flex; align-items: center; gap: 20px; }
.navlinks { display: flex; gap: 2px; flex: 1; justify-content: center; }
.navlink { display: inline-flex; align-items: center; gap: 7px; height: 36px; padding: 0 12px; border-radius: 9px; color: var(--muted); font-size: 14px; font-weight: 550; }
.navlink.active { color: var(--fg); background: var(--surface); box-shadow: 0 0 0 1px var(--border), var(--shadow-sm); }
.navlink.active svg { color: var(--accent); }
.avatar { width: 34px; height: 34px; border-radius: 999px; display: grid; place-items: center; background: linear-gradient(135deg, var(--accent), #F59E0B);
  color: #fff; font-weight: 700; font-size: 13px; letter-spacing: 0.02em; }
.ask { padding: 16px; }
.ask-row { display: flex; align-items: center; gap: 12px; }
.ask-input { flex: 1; min-width: 0; height: 46px; font-size: 17px; display: flex; align-items: center; white-space: nowrap; overflow: hidden; }
.ask-examples { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
.empty { text-align: center; padding: 36px 16px; color: var(--muted); }
.empty-icon { width: 44px; height: 44px; margin: 0 auto 12px; border-radius: 14px; display: grid; place-items: center; background: var(--surface-2); color: var(--subtle); }
.spinner { width: 16px; height: 16px; border-radius: 999px; border: 2px solid currentColor; border-right-color: transparent; }
.link { color: var(--accent-ink); font-weight: 600; }
.toast { display: flex; gap: 10px; align-items: flex-start; padding: 13px 14px; border-radius: 13px; background: var(--fg); color: var(--bg);
  box-shadow: var(--shadow-lg); font-size: 14px; max-width: 400px; }
.caret { display: inline-block; width: 1.5px; height: 1.15em; background: var(--accent); margin-left: 1px; vertical-align: -0.18em; }
`

function useFonts() {
  const [handle] = useState(() => delayRender('Chargement des polices'))
  useEffect(() => {
    const sample = 'Caffein à é è ç € 0123456789'
    Promise.all([
      document.fonts.load('400 20px "DM Sans Variable"', sample),
      document.fonts.load('650 20px "DM Sans Variable"', sample),
      document.fonts.load('400 20px "JetBrains Mono"', sample),
      document.fonts.load('500 20px "JetBrains Mono"', sample),
    ]).then(() => document.fonts.ready).finally(() => continueRender(handle))
  }, [handle])
}

// ── Composition ───────────────────────────────────────────────────────
export function MesVues() {
  useFonts()
  return (
    <AbsoluteFill className="app">
      <style>{CSS}</style>
      <Series>
        <Series.Sequence durationInFrames={D.title}><Fade duration={D.title} fadeIn={0}><TitleScene /></Fade></Series.Sequence>
        <Series.Sequence durationInFrames={D.demo}><Fade duration={D.demo}><DemoScene /></Fade></Series.Sequence>
        <Series.Sequence durationInFrames={D.explain}><Fade duration={D.explain}><ExplainScene /></Fade></Series.Sequence>
        <Series.Sequence durationInFrames={D.roadmap}><Fade duration={D.roadmap}><RoadmapScene /></Fade></Series.Sequence>
        <Series.Sequence durationInFrames={D.end}><Fade duration={D.end} fadeOut={0}><EndScene /></Fade></Series.Sequence>
      </Series>
    </AbsoluteFill>
  )
}

// Fondu de début et de fin de scène (≈ 400 ms) sur le fond de l'application
function Fade({ duration, fadeIn = 12, fadeOut = 12, children }) {
  const f = useCurrentFrame()
  const opacity = Math.min(fadeIn ? ramp(f, 0, fadeIn) : 1, fadeOut ? ramp(f, duration - fadeOut, duration, 1, 0) : 1)
  return <AbsoluteFill style={{ opacity, background: 'var(--bg)' }}>{children}</AbsoluteFill>
}

function LogoMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="17" fill="#E8510E" />
      <path d="M32 13c-9.5 0-16 8.6-16 19s6.5 19 16 19 16-8.6 16-19-6.5-19-16-19Z" fill="#fff" />
      <path d="M33.5 15.5c-5 5-5 11.5-1.5 16.5s3.5 11.5-1.5 16.5" fill="none" stroke="#E8510E" strokeWidth="4" strokeLinecap="round" />
    </svg>
  )
}

function Logo({ size = 28 }) {
  return (
    <span className="row" style={{ gap: size * 0.32 }}>
      <LogoMark size={size} />
      <span style={{ fontWeight: 700, fontSize: size * 0.68, letterSpacing: '-0.035em', lineHeight: 1 }}>caffein</span>
    </span>
  )
}

const rise = (p, dist = 14) => ({ opacity: p, transform: `translateY(${(1 - p) * dist}px)` })

// ── 1. Titre ──────────────────────────────────────────────────────────
function TitleScene() {
  const f = useCurrentFrame()
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 34 }}>
        <div style={rise(ramp(f, 2, 20), 18)}><LogoMark size={112} /></div>
        <h1 style={{ ...rise(ramp(f, 10, 28)), fontSize: 104, fontWeight: 650, letterSpacing: '-0.035em', lineHeight: 1 }}>
          Caffein <span style={{ color: 'var(--accent)' }}>·</span> Mes vues
        </h1>
        <p style={{ ...rise(ramp(f, 20, 38)), fontSize: 46, color: 'var(--muted)', letterSpacing: '-0.01em' }}>
          Votre tableau de bord, à portée de mots
        </p>
      </div>
    </AbsoluteFill>
  )
}

// ── 2 à 6. Démonstration de la page « Mes vues » ──────────────────────
// La page est dessinée à 1280 × 720 (taille d'un écran de portable) puis agrandie × 1,5 : 15 px → 22,5 px.
const SCALE = 1.5
const STEP_START = [18, 284, 540, 718]
const STEP_FPC = [1.25, 1.2, 1.6, 1.3] // images par caractère tapé
const STEPS = data.steps.map((s, i) => {
  const typeStart = STEP_START[i]
  const typeEnd = typeStart + Math.ceil(s.text.length * STEP_FPC[i])
  return { ...s, typeStart, fpc: STEP_FPC[i], typeEnd, press: typeEnd + 8, show: typeEnd + 22 }
})
const [S1, S2, S3, S4] = STEPS
const SAVE = { press: 905, form: 911, typeStart: 918, fpc: 1.8, name: 'Pilotage mensuel' }
SAVE.typeEnd = SAVE.typeStart + Math.ceil(SAVE.name.length * SAVE.fpc)
SAVE.confirm = SAVE.typeEnd + 10
SAVE.saved = SAVE.confirm + 8

// Position de la « caméra » (défilement de la page, en pixels de la page)
const CAMERA = [
  [0, 0], [S1.show + 10, 0], [S1.show + 40, 270], [S2.typeStart - 22, 270], [S2.typeStart, 120],
  [S2.show + 10, 120], [S2.show + 40, 660], [S3.typeStart - 25, 660], [S3.typeStart, 120],
  [S3.show - 3, 120], [S3.show + 27, 310], [S4.typeStart - 23, 310], [S4.typeStart, 120], [D.demo, 120],
]

const CAPTIONS = [
  [8, S1.show - 4, 'Écrivez simplement ce que vous voulez voir.'],
  [S1.show + 2, S2.typeStart - 10, 'Caffein compose la page avec vos propres chiffres.'],
  [S2.typeStart - 4, S3.typeStart - 14, 'Une phrase de plus, une carte de plus.'],
  [S3.typeStart - 8, S4.typeStart - 14, `Une carte en trop${NNB}? Demandez de la retirer.`],
  [S4.typeStart - 8, SAVE.press - 4, `Lecture seule${NB}: l’IA ne modifie jamais vos données.`],
  [SAVE.press + 2, D.demo - 6, 'La vue se recharge sans rappeler l’IA.'],
]

const MESSAGES = {
  composed: `Compris${NB}: voici votre vue.`,
  added: 'C’est ajouté à la vue.',
  removed: 'C’est retiré de la vue.',
  read_only: `Cette page ne fait qu’afficher${NB}: pour modifier une facture ou un client, ouvrez la page Factures.`,
}
const BY = { claude: 'Composé par Claude', heuristique: 'Analyse locale' }

function DemoScene() {
  const f = useCurrentFrame()
  const cam = interpolate(f, CAMERA.map((k) => k[0]), CAMERA.map((k) => k[1]), { ...CLAMP, easing: Easing.inOut(Easing.cubic) })
  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', inset: 0, width: 1280, height: 720, transform: `scale(${SCALE})`, transformOrigin: '0 0', overflow: 'hidden', background: 'var(--bg)' }}>
        <div style={{ transform: `translateY(${-cam}px)` }}>
          <div style={{ height: 63 }} />
          <div className="container">
            <div className="page">
              <PageHeader />
              <AskBar f={f} />
              <Feedback f={f} />
              <ViewsBar f={f} />
              <WidgetGrid f={f} />
              <p className="xsmall muted" style={{ marginTop: 18 }}>
                L’IA ne voit jamais vos chiffres{NB}: elle choisit des cartes dans un catalogue, et Caffein calcule les données sur votre serveur. Cette page ne modifie rien.
              </p>
            </div>
          </div>
        </div>
        <Navbar />
        <Toast f={f} />
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 170, background: 'linear-gradient(to bottom, rgba(250, 250, 248, 0), rgba(250, 250, 248, 0.92) 55%)' }} />
      <Caption f={f} items={CAPTIONS} />
    </AbsoluteFill>
  )
}

const NAV = [
  ['Accueil', Home], ['Mes vues', Sparkles], ['TVA', Percent], ['Factures', ReceiptText],
  ['Documents', FileStack], ['URSSAF', Landmark], ['Automatisations', Bot],
]

function Navbar() {
  return (
    <header className="navbar">
      <div className="container navbar-inner">
        <Logo size={28} />
        <nav className="navlinks">
          {NAV.map(([label, Icon]) => (
            <span key={label} className={`navlink ${label === 'Mes vues' ? 'active' : ''}`}><Icon size={16} />{label}</span>
          ))}
        </nav>
        <div className="row" style={{ gap: 6 }}>
          <span className="icon-btn"><Moon size={18} /></span>
          <span className="avatar">AD</span>
        </div>
      </div>
    </header>
  )
}

function PageHeader() {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">Mes vues</h1>
        <p className="page-sub">Dites ce que vous voulez voir{NB}: Caffein compose la page avec vos chiffres.</p>
      </div>
      <span className="badge outline"><Cpu size={13} />Analyse locale</span>
    </div>
  )
}

// État de la barre de demande à l'image f : texte, chargement, étape en cours
function askState(f) {
  let step = null
  for (const s of STEPS) if (f >= s.typeStart) step = s
  if (!step) return { text: '', busy: false, step: null }
  const busy = f >= step.press && f < step.show
  const done = f >= step.show
  const text = done ? (step.understood ? '' : step.text) : typed(f, step.typeStart, step.text, step.fpc)
  return { text, busy, step, typing: f < step.typeEnd }
}

function Spinner({ f, size = 16 }) {
  return <span className="spinner" style={{ width: size, height: size, transform: `rotate(${f * 17}deg)` }} />
}

// Appui sur un bouton : léger enfoncement et halo orange (sans curseur de souris)
function pressStyle(f, at) {
  const scale = interpolate(f, [at - 3, at, at + 6], [1, 0.95, 1], CLAMP)
  const r = ramp(f, at, at + 16, 0, 12)
  const a = ramp(f, at, at + 16, 0.45, 0)
  return { transform: `scale(${scale})`, boxShadow: `0 0 0 ${r}px rgba(232, 81, 14, ${a}), 0 6px 16px -8px rgba(232, 81, 14, 0.7)` }
}

function AskBar({ f }) {
  const { text, busy, step, typing } = askState(f)
  const focused = f >= S1.typeStart - 6 && f < SAVE.press
  const enabled = text.trim().length >= 3 && !busy
  const caretOn = focused && (typing || Math.floor(f / 16) % 2 === 0)
  // Le bouton « Afficher » s'anime entre la fin de la frappe et le clic
  const glow = step && f >= step.typeEnd && f < step.press
    ? { boxShadow: `0 0 0 ${3 + 3 * Math.sin((f - step.typeEnd) / 3)}px rgba(232, 81, 14, 0.18), 0 6px 16px -8px rgba(232, 81, 14, 0.7)` } : {}
  const press = step && f >= step.press - 3 && f < step.press + 16 ? pressStyle(f, step.press) : {}
  return (
    <div className="card ask" style={focused ? { borderColor: 'var(--accent)', boxShadow: '0 0 0 3px var(--accent-soft)' } : null}>
      <div className="ask-row">
        <WandSparkles size={20} color="var(--accent)" style={{ flex: 'none' }} />
        <div className="ask-input">
          {text
            ? <span>{text}{caretOn && <span className="caret" />}</span>
            : <span style={{ color: 'var(--subtle)' }}>{caretOn && <span className="caret" style={{ marginLeft: 0, marginRight: 1 }} />}Ex.{NB}: montre-moi mon chiffre d’affaires par mois et mes factures impayées</span>}
        </div>
        <span className="btn primary" style={{ opacity: enabled || busy ? 1 : 0.5, ...glow, ...press }}>
          {busy ? <Spinner f={f} /> : <Sparkles size={16} />} Afficher
        </span>
      </div>
      <div className="chips ask-examples">
        {['Mon chiffre d’affaires par mois et mes impayés', 'Ajoute mes dépenses par catégorie cette année', 'Mes 5 plus gros clients', 'La TVA du trimestre', 'Mes prochaines échéances']
          .map((label) => <span key={label} className="chip" style={{ opacity: busy ? 0.5 : 1 }}>{label}</span>)}
      </div>
    </div>
  )
}

function Feedback({ f }) {
  let cur = null
  for (const s of STEPS) if (f >= s.show) cur = s
  const height = ramp(f, S1.show, S1.show + 10) * 63
  if (!cur) return <div style={{ height }} />
  const pending = STEPS.find((s) => f >= s.press && f < s.show)
  const opacity = pending ? ramp(f, pending.press, pending.press + 5, 1, 0) : ramp(f, cur.show, cur.show + 9)
  return (
    <div style={{ height, paddingTop: 14, overflow: 'hidden' }}>
      <div className={`alert ${cur.understood ? 'info' : 'warn'}`} style={{ ...rise(opacity, 6), alignItems: 'center' }}>
        <Bot size={18} style={{ marginTop: 0 }} />
        <span className="grow truncate">{MESSAGES[cur.message]}</span>
        <span className="xsmall muted">{BY[cur.composed_by]}</span>
      </div>
    </div>
  )
}

function ViewsBar({ f }) {
  const hasWidgets = f >= S1.show
  const naming = f >= SAVE.form && f < SAVE.saved
  const saved = f >= SAVE.saved
  const name = typed(f, SAVE.typeStart, SAVE.name, SAVE.fpc)
  const savedIn = ramp(f, SAVE.saved, SAVE.saved + 12)
  return (
    <div className="row between" style={{ margin: '22px 0 14px', gap: 12, height: 34 }}>
      <div className="chips">
        {saved
          ? <span className="chip active" style={{ ...rise(savedIn, 6), transform: `scale(${0.9 + 0.1 * savedIn})` }}><LayoutGrid size={14} /> {SAVE.name}</span>
          : <span className="small muted">Aucune vue enregistrée pour l’instant.</span>}
      </div>
      {hasWidgets && (
        <div className="row" style={{ ...rise(ramp(f, S1.show, S1.show + 10), 6) }}>
          {/* Vue enregistrée et inchangée : seul « Supprimer la vue » s'ajoute (« Mettre à jour » apparaît après une modification) */}
          {saved && (
            <span className="btn sm ghost danger" style={{ opacity: savedIn }}><Trash2 size={15} /> Supprimer la vue</span>
          )}
          {naming ? (
            <div className="row" style={rise(ramp(f, SAVE.form, SAVE.form + 8), 4)}>
              <div className="input" style={{ width: 220 }}>
                {name
                  ? <span>{name}{f < SAVE.typeEnd + 6 && <span className="caret" />}</span>
                  : <span style={{ color: 'var(--subtle)' }}><span className="caret" style={{ marginLeft: 0 }} />Ex.{NB}: Pilotage mensuel</span>}
              </div>
              <span className="btn sm primary" style={{ opacity: name ? 1 : 0.5, ...(f >= SAVE.confirm - 3 ? pressStyle(f, SAVE.confirm) : {}) }}>Enregistrer</span>
              <span className="btn sm ghost">Annuler</span>
            </div>
          ) : (
            <span className="btn sm" style={f >= SAVE.press - 3 && f < SAVE.form ? { ...pressStyle(f, SAVE.press), borderColor: 'var(--accent)' } : null}>
              <Save size={15} /> Enregistrer la vue
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ── Grille de cartes : 12 colonnes de la page, positions animées quand une carte disparaît ──
const GAP = 16
const COL = (1152 - 11 * GAP) / 12
const spanW = (n) => n * COL + (n - 1) * GAP
const colX = (start) => start * (COL + GAP)
const H = { revenue: 378, unpaid: 424, kpi: 140, expenses: 378 }
const LAYOUT_B = { revenue: [0, 0], unpaid: [colX(6), 0], kpi: [0, H.unpaid + GAP], expenses: [colX(3), H.unpaid + GAP] }
const LAYOUT_C = { revenue: [0, 0], kpi: [colX(6), 0], expenses: [0, H.revenue + GAP] }

function WidgetGrid({ f }) {
  const { fps } = useVideoConfig()
  const reflow = spring({ frame: f - (S3.show + 8), fps, config: { damping: 200 }, durationInFrames: 24 })
  const pos = (key) => {
    const b = LAYOUT_B[key]
    const c = LAYOUT_C[key] || b
    return [lerp(b[0], c[0], reflow), lerp(b[1], c[1], reflow)]
  }
  const height = f < S1.show ? 216
    : f < S2.show ? H.unpaid
      : f < S3.show ? lerp(H.unpaid, H.unpaid + GAP + H.expenses, ramp(f, S2.show, S2.show + 12))
        : lerp(H.unpaid + GAP + H.expenses, H.revenue + GAP + H.expenses, reflow)
  const card = (key, inAt, span, outAt, body) => {
    if (f < inAt) return null
    const a = ramp(f, inAt, inAt + 12)
    const out = outAt ? ramp(f, outAt, outAt + 10, 1, 0) : 1
    if (out <= 0) return null
    const [x, y] = pos(key)
    return (
      <div key={key} style={{ position: 'absolute', left: x, top: y, width: spanW(span), height: H[key], opacity: a * out,
        transform: `translateY(${(1 - a) * 10}px) scale(${1 - 0.03 * (1 - out)})` }}>
        {body}
      </div>
    )
  }
  const emptyOut = ramp(f, S1.show - 2, S1.show + 6, 1, 0)
  return (
    <div style={{ position: 'relative', height }}>
      {emptyOut > 0 && (
        <div className="card" style={{ position: 'absolute', inset: 0, height: 216, opacity: emptyOut }}>
          <div className="empty">
            <div className="empty-icon"><Sparkles size={20} /></div>
            <div style={{ fontWeight: 600, color: 'var(--fg)' }}>Votre page est vide</div>
            <div className="small" style={{ marginTop: 4 }}>Écrivez ce que vous voulez voir, ou choisissez un exemple ci-dessus.</div>
          </div>
        </div>
      )}
      {card('revenue', S1.show, 6, null, <RevenueCard f={f} start={S1.show + 4} />)}
      {card('unpaid', S1.show + 5, 6, S3.show, <UnpaidCard f={f} start={S1.show + 9} />)}
      {card('kpi', S2.show, 3, null, <KpiCard />)}
      {card('expenses', S2.show + 5, 6, null, <ExpensesCard f={f} start={S2.show + 9} />)}
    </div>
  )
}

function RemoveButton({ style }) {
  return <span className="icon-btn" style={{ opacity: 0.55, ...style }}><X size={16} /></span>
}

function WidgetCard({ title, children }) {
  return (
    <section className="card" style={{ height: '100%' }}>
      <div className="card-head">
        <h2 className="card-title">{title}</h2>
        <RemoveButton />
      </div>
      {children}
    </section>
  )
}

function ChartHead({ legend }) {
  return (
    <div className="row between" style={{ marginBottom: 14 }}>
      {legend ? (
        <div className="legend">
          {legend.map((s) => <span key={s.key}><span className="key" style={{ background: s.color }} />{s.label}</span>)}
        </div>
      ) : <span />}
      <span className="btn sm ghost"><Table2 size={15} /> Tableau</span>
    </div>
  )
}

const REVENUE_SERIES = [
  { key: 'invoiced', label: 'Facturé', color: 'var(--series-collected)' },
  { key: 'paid', label: 'Encaissé', color: 'var(--series-deductible)' },
]

function RevenueCard({ f, start }) {
  return (
    <WidgetCard title="Chiffre d’affaires HT · 12 derniers mois">
      <ChartHead legend={REVENUE_SERIES} />
      <BarChart f={f} start={start} rows={data.revenue_by_month} series={REVENUE_SERIES} ticks={[0, 2, 4, 6, 8, 11]} />
    </WidgetCard>
  )
}

function ExpensesCard({ f, start }) {
  const series = [{ key: 'amount', label: 'Montant HT', color: 'var(--series-collected)' }]
  return (
    <WidgetCard title="Dépenses HT par catégorie · cette année">
      <ChartHead />
      <BarChart f={f} start={start} rows={data.expenses_by_category} series={series} ticks={data.expenses_by_category.map((_, i) => i)} stagger={4} />
    </WidgetCard>
  )
}

// Graduations « rondes » de l'axe des montants (comme Recharts : 5 graduations)
function niceScale(max) {
  const raw = max / 4
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 1.5, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw)
  return { step, top: step * 4 }
}

function barPath(x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`
}

// Barres : ≤ 24 px, extrémité arrondie 4 px, 2 px d'écart, grille fine (spécifications de charts.jsx)
function BarChart({ f, start, rows, series, ticks, width = 526, height = 240, stagger = 2 }) {
  const { fps } = useVideoConfig()
  const left = 56; const right = 4; const top = 8; const bottom = 26
  const pw = width - left - right
  const ph = height - top - bottom
  const max = Math.max(...rows.flatMap((r) => series.map((s) => r[s.key])))
  const { step, top: yMax } = niceScale(max)
  const cat = pw / rows.length
  const inner = cat * 0.78
  const bw = Math.min(24, (inner - 2 * (series.length - 1)) / series.length)
  const groupW = bw * series.length + 2 * (series.length - 1)
  const y = (v) => top + ph - (v / yMax) * ph
  return (
    <svg width={width} height={height} style={{ overflow: 'visible' }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <g key={i}>
          <line x1={left} x2={width - right} y1={y(i * step)} y2={y(i * step)} stroke={i ? 'var(--grid)' : 'var(--border)'} />
          <text x={left - 8} y={y(i * step) + 4} textAnchor="end" fontSize={12} fill="var(--muted)">{compactMoney(i * step)}</text>
        </g>
      ))}
      {rows.map((row, i) => {
        const grow = spring({ frame: f - start - i * stagger, fps, config: { damping: 18, stiffness: 120, mass: 0.6 } })
        return (
          <g key={row.label}>
            {series.map((s, j) => {
              const h = (row[s.key] / yMax) * ph * Math.max(0, grow)
              if (h <= 0.2) return null
              const x = left + i * cat + (cat - groupW) / 2 + j * (bw + 2)
              return <path key={s.key} d={barPath(x, top + ph - h, bw, h, 4)} fill={s.color} />
            })}
            {ticks.includes(i) && (
              <text x={left + i * cat + cat / 2} y={height - 6} textAnchor="middle" fontSize={12} fill="var(--muted)">{row.label}</text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function UnpaidCard({ f, start }) {
  const { rows, count, total } = data.unpaid_invoices
  return (
    <WidgetCard title="Factures à encaisser">
      <table className="table">
        <thead>
          <tr><th>Client</th><th className="right">Total TTC</th><th>Échéance</th></tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id} style={{ opacity: ramp(f, start + i * 3, start + i * 3 + 10) }}>
              <td style={{ maxWidth: 220 }}>
                <div className="truncate">{row.client}</div>
                <div className="xsmall muted mono truncate">{row.number}</div>
              </td>
              <td className="right mono">{money(row.total)}</td>
              <td>
                {row.status === 'overdue' ? (
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
                    <span className="badge bad"><AlertTriangle size={13} />En retard</span>
                    <span className="xsmall muted">depuis {row.days_overdue} {row.days_overdue > 1 ? 'jours' : 'jour'}</span>
                  </span>
                ) : <span className="small">{frDate(row.due_date)}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row between small muted" style={{ marginTop: 12, opacity: ramp(f, start + 12, start + 22) }}>
        <span>{count} factures · {money(total)}</span>
        <span className="link small">Tout voir</span>
      </div>
    </WidgetCard>
  )
}

function KpiCard() {
  const { value, count } = data.kpi_to_collect
  return (
    <div style={{ position: 'relative', height: '100%' }}>
      <RemoveButton style={{ position: 'absolute', top: 10, right: 10 }} />
      <div className="card stat">
        <div className="stat-label"><span className="stat-icon"><Wallet size={16} /></span>À encaisser</div>
        <div className="stat-value">{money(value)}</div>
        <div className="stat-foot">{count} factures</div>
      </div>
    </div>
  )
}

function Toast({ f }) {
  if (f < SAVE.saved) return null
  const a = Math.min(ramp(f, SAVE.saved, SAVE.saved + 8), ramp(f, SAVE.saved + 80, SAVE.saved + 90, 1, 0))
  return (
    <div className="toast" style={{ position: 'absolute', left: 20, bottom: 92, ...rise(a, 8) }}>
      <CheckCircle2 size={18} color="#4ade80" />
      <span>Vue «{NNB}{SAVE.name}{NNB}» enregistrée{NB}: elle se recharge sans l’IA.</span>
    </div>
  )
}

// Sous-titre en bas de l'écran
function Caption({ f, items }) {
  const cur = items.find(([a, b]) => f >= a && f < b)
  if (!cur) return null
  const [a, b, text] = cur
  const o = Math.min(ramp(f, a, a + 9), ramp(f, b - 9, b, 1, 0))
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom: 44, display: 'flex', justifyContent: 'center', ...rise(o, 8) }}>
      <div style={{ background: 'rgba(22, 22, 20, 0.88)', color: '#F5F5F2', fontSize: 34, fontWeight: 550, padding: '14px 30px', borderRadius: 16, letterSpacing: '-0.01em', lineHeight: 1.3 }}>
        {text}
      </div>
    </div>
  )
}

// ── 7. Comment ça marche ──────────────────────────────────────────────
const FLOW = [
  { icon: MessageSquareText, label: 'Votre demande', detail: `«${NNB}Montre-moi mon CA par mois${NNB}»` },
  { icon: Sparkles, label: 'IA ou analyse locale', detail: 'Claude, ou des mots-clés sans clé d’API' },
  { icon: Braces, label: 'Description JSON (catalogue fermé)', detail: 'Des briques parmi 8 sources connues', mono: true },
  { icon: ShieldCheck, label: 'Validation', detail: 'Tout ce qui est inconnu est écarté' },
  { icon: Server, label: 'Données calculées sur votre serveur', detail: 'Mêmes règles que le reste de Caffein' },
  { icon: LayoutDashboard, label: 'Affichage', detail: 'Les composants de l’application' },
]
const NODE_W = 250
const NODE_GAP = 44
const NODE_X = (i) => 100 + i * (NODE_W + NODE_GAP)
const NODE_IN = (i) => 22 + i * 22

function SceneTitle({ f, title, sub }) {
  return (
    <div style={{ position: 'absolute', top: 110, left: 0, right: 0, textAlign: 'center' }}>
      <h1 style={{ ...rise(ramp(f, 0, 14)), fontSize: 64, fontWeight: 650, letterSpacing: '-0.03em' }}>{title}</h1>
      <p style={{ ...rise(ramp(f, 6, 20)), fontSize: 32, color: 'var(--muted)', marginTop: 14 }}>{sub}</p>
    </div>
  )
}

function Zone({ f, at, from, to, label, color, soft }) {
  const a = ramp(f, at, at + 15)
  const x = NODE_X(from) - 16
  const w = NODE_X(to) + NODE_W + 16 - x
  return (
    <div style={{ position: 'absolute', left: x, top: 318, width: w, height: 404, borderRadius: 24, background: soft, border: `1.5px dashed ${color}`, opacity: a }}>
      <div style={{ position: 'absolute', top: 14, left: 0, right: 0, textAlign: 'center', fontSize: 22, fontWeight: 650, color, letterSpacing: '0.02em' }}>{label}</div>
    </div>
  )
}

function ExplainScene() {
  const f = useCurrentFrame()
  const hl = ramp(f, 176, 192)
  return (
    <AbsoluteFill>
      <SceneTitle f={f} title="Comment ça marche" sub="L’IA assemble des briques, elle ne fabrique rien." />
      <Zone f={f} at={NODE_IN(2) + 6} from={1} to={2} label="Côté IA" color="var(--accent-ink)" soft="rgba(232, 81, 14, 0.05)" />
      <Zone f={f} at={NODE_IN(4) + 6} from={3} to={4} label="Votre serveur" color="var(--info)" soft="rgba(37, 99, 235, 0.05)" />
      {FLOW.map((node, i) => {
        const a = ramp(f, NODE_IN(i), NODE_IN(i) + 14)
        const lit = ramp(f, NODE_IN(i) + 4, NODE_IN(i) + 16)
        const Icon = node.icon
        return (
          <div key={node.label}>
            <div className="card" style={{ position: 'absolute', left: NODE_X(i), top: 372, width: NODE_W, height: 320, padding: 24,
              ...rise(a, 18), borderColor: lit > 0.5 ? 'rgba(232, 81, 14, 0.45)' : 'var(--border)' }}>
              <div style={{ width: 56, height: 56, borderRadius: 16, display: 'grid', placeItems: 'center', background: 'var(--accent-soft)', color: 'var(--accent)' }}>
                <Icon size={28} />
              </div>
              <div style={{ fontSize: 27, fontWeight: 650, lineHeight: 1.2, marginTop: 20, letterSpacing: '-0.015em' }}>{node.label}</div>
              <div style={{ fontSize: 22, color: 'var(--muted)', lineHeight: 1.35, marginTop: 12 }}>{node.detail}</div>
            </div>
            {i < FLOW.length - 1 && (
              <div style={{ position: 'absolute', left: NODE_X(i) + NODE_W + 6, top: 516, width: NODE_GAP - 12, display: 'grid', placeItems: 'center',
                opacity: ramp(f, NODE_IN(i) + 12, NODE_IN(i) + 22), transform: `translateX(${ramp(f, NODE_IN(i) + 12, NODE_IN(i) + 22, -8, 0)}px)`, color: 'var(--accent)' }}>
                <ArrowRight size={30} strokeWidth={2.4} />
              </div>
            )}
          </div>
        )
      })}
      <div style={{ position: 'absolute', top: 790, left: 0, right: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18 }}>
        <div style={{ ...rise(hl, 12), transform: `translateY(${(1 - hl) * 12}px) scale(${0.96 + 0.04 * hl})`, display: 'flex', alignItems: 'center', gap: 16,
          background: 'var(--fg)', color: '#F5F5F2', padding: '18px 34px', borderRadius: 999, fontSize: 40, fontWeight: 650, letterSpacing: '-0.02em' }}>
          <EyeOff size={36} color="#FF8A55" /> L’IA ne voit jamais vos chiffres
        </div>
        <p style={{ ...rise(ramp(f, 190, 206), 8), fontSize: 26, color: 'var(--muted)' }}>
          Elle ne reçoit que la demande, le catalogue et la vue en cours{NNB}; les montants restent sur votre serveur.
        </p>
      </div>
    </AbsoluteFill>
  )
}

// ── 8. Feuille de route ───────────────────────────────────────────────
const ROADMAP = [
  { title: 'Lecture seule', text: `«${NNB}Montre-moi…${NNB}» ne fait qu’afficher${NB}: aucun risque.`, done: true },
  { title: 'Vues enrichies', text: 'Réorganiser les cartes, épingler une vue sur l’accueil, la partager.' },
  { title: 'Formulaires préremplis', text: 'L’IA remplit le vrai formulaire, vous vérifiez et enregistrez.' },
  { title: 'Actions avec confirmation', text: `Relancer, dupliquer, créer un avoir${NB}: les règles métier d’abord.` },
]
const CARD_W = 400
const CARD_GAP = 40
const CARD_X = (i) => 100 + i * (CARD_W + CARD_GAP)

function RoadmapScene() {
  const f = useCurrentFrame()
  const line = ramp(f, 16, 70, 0, 1, Easing.inOut(Easing.cubic))
  return (
    <AbsoluteFill>
      <SceneTitle f={f} title="La suite, étape par étape" sub="Chaque étape ajoute du pouvoir, jamais sans votre accord." />
      <div style={{ position: 'absolute', left: CARD_X(0) + 28, top: 429, height: 3, width: (CARD_X(3) - CARD_X(0)) * line, background: 'var(--border-strong)', borderRadius: 2 }} />
      {ROADMAP.map((step, i) => {
        const a = ramp(f, 16 + i * 12, 30 + i * 12)
        return (
          <div key={step.title}>
            <div style={{ position: 'absolute', left: CARD_X(i) + 16, top: 418, width: 26, height: 26, borderRadius: 999, opacity: a,
              background: step.done ? 'var(--accent)' : 'var(--surface)', border: `3px solid ${step.done ? 'var(--accent)' : 'var(--border-strong)'}`,
              display: 'grid', placeItems: 'center', color: '#fff' }}>
              {step.done && <Check size={15} strokeWidth={3.5} />}
            </div>
            <div className="card" style={{ position: 'absolute', left: CARD_X(i), top: 472, width: CARD_W, height: 300, padding: 30, ...rise(a, 18),
              borderColor: step.done ? 'rgba(232, 81, 14, 0.45)' : 'var(--border)' }}>
              <div className="row between">
                <span style={{ fontSize: 22, fontWeight: 650, color: step.done ? 'var(--accent-ink)' : 'var(--subtle)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                  Étape {i + 1}
                </span>
                {step.done
                  ? <span className="badge" style={{ height: 36, padding: '0 14px', fontSize: 20, background: 'var(--accent-soft)', color: 'var(--accent-ink)' }}><Check size={18} strokeWidth={3} /> Prototype</span>
                  : <span className="badge outline" style={{ height: 36, padding: '0 14px', fontSize: 20 }}>À venir</span>}
              </div>
              <div style={{ fontSize: 34, fontWeight: 650, marginTop: 26, letterSpacing: '-0.02em', lineHeight: 1.15 }}>{step.title}</div>
              <div style={{ fontSize: 24, color: 'var(--muted)', marginTop: 14, lineHeight: 1.4 }}>{step.text}</div>
            </div>
          </div>
        )
      })}
    </AbsoluteFill>
  )
}

// ── Fin ───────────────────────────────────────────────────────────────
function EndScene() {
  const f = useCurrentFrame()
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 30 }}>
        <div style={rise(ramp(f, 0, 16), 14)}><Logo size={88} /></div>
        <p style={{ ...rise(ramp(f, 8, 24)), fontSize: 44, fontWeight: 550, letterSpacing: '-0.015em' }}>
          Caffein — logiciel libre (AGPL-3.0)
        </p>
      </div>
    </AbsoluteFill>
  )
}
