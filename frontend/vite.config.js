// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false, // désactivé en prod pour la sécurité
  },
  server: {
    port: 5173,
    open: true,
    // en développement, l'API Python tourne sur :8000
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
