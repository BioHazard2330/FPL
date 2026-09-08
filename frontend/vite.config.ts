import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const dirname = import.meta.dirname

// FPL Agent frontend (Phase 8.2 Stage 2) - the Python backend stays the
// authoritative source of truth (optimizer, projections, decision engine);
// this dev server only proxies /api and /events to the real live-server
// process (`fpl live-server`, real default port 8877) so the SAME real
// payload builders and SSE stream this project already has power the React
// app - never a second, duplicated backend. `VITE_API_PORT` overrides the
// target port for local dev when a second, non-scheduled instance is
// running on a different port (the real scheduled `FPLAgentLiveServer` task
// already owns 8877 on this machine - never kill/restart that one for dev
// testing, point a throwaway second instance at a different port instead).
const apiPort = process.env.VITE_API_PORT ?? '8877'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true },
      '/events': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true, ws: false },
      // Real, server-cached crest PNGs (`data/crests/`, `ingestion/
      // crest_assets.py`) - they only exist on the backend's own data_dir,
      // never in `frontend/public/`. Without this, Vite's dev-server SPA
      // fallback silently served `index.html` (200, `text/html`) for any
      // `/crests/*.png` request - a real bug found live via visual QA
      // (every crest badge rendered blank, `<img>` failing to decode HTML
      // as an image, no console error either since the request itself
      // "succeeded").
      '/crests': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true },
      '/live_snapshot.json': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true },
    },
  },
})
