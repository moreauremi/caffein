// SPDX-License-Identifier: AGPL-3.0-or-later
// Reconstruit apercu.html (un seul fichier, React compris) à partir de CaffeinPromo.jsx.
//   cd frontend && npm ci && cd ..        (une fois : fournit React)
//   node docs/presentation/build.mjs
import { execFileSync } from 'node:child_process'
import { existsSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const modules = resolve(here, '../../frontend/node_modules')
if (!existsSync(resolve(modules, 'react-dom'))) {
  console.error("React est introuvable : lancez d'abord « cd frontend && npm ci ».")
  process.exit(1)
}

// esbuild : celui de la variable ESBUILD s'il est fourni, sinon téléchargé par npx.
const [cmd, ...pre] = process.env.ESBUILD ? [process.env.ESBUILD] : ['npx', '--yes', 'esbuild@0.28.2']
const js = execFileSync(cmd, [...pre, 'apercu.jsx', '--bundle', '--minify', '--jsx=automatic', '--legal-comments=none',
  '--define:process.env.NODE_ENV="production"', '--log-level=warning'], {
  cwd: here, env: { ...process.env, NODE_PATH: modules }, maxBuffer: 64 * 1024 * 1024,
}).toString()

const html = `<!doctype html>
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Fichier généré à partir de CaffeinPromo.jsx par build.mjs (voir README.md) : ne pas modifier à la main. -->
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Caffein, présentation</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#ECECE8;font-family:system-ui,sans-serif}#root{width:min(1280px,calc(100vw - 32px));padding:16px 0}</style>
</head><body><div id="root"></div><script>${js.replaceAll('</script', '<\\/script')}</script></body></html>
`
writeFileSync(resolve(here, 'apercu.html'), html)
console.log(`apercu.html reconstruit (${Math.round(html.length / 1024)} Ko).`)
