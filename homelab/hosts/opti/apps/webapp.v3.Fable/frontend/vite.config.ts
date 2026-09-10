import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { existsSync, readFileSync } from 'node:fs';

// Dev server proxies /api (and the legacy/standalone paths) to a real backend, so
// `npm run dev` works against live data without running the backend locally.
// Default target is the live opti backend (the app tier moved off rpi 2026-09-10); VITE_PROXY_TARGET=http://127.0.0.1:3000 (or the
// same URL in a git-ignored `.proxy-target` file beside this config) points it at a
// local `node server.js` — needed to exercise the v3-only routes (SSE, incidents,
// hosts) before go-live. Production never sees this — the built app is served by
// the Fastify backend itself.
const fromFile = existsSync(new URL('./.proxy-target', import.meta.url))
  ? readFileSync(new URL('./.proxy-target', import.meta.url), 'utf8').trim()
  : '';
const LIVE = process.env.VITE_PROXY_TARGET ?? (fromFile || 'https://192.168.1.11:8443');
// /streams is a v3 route now (the v1 player lives under /legacy/streams/); /hls is the video.
const proxied = ['/api', '/legacy', '/architecture', '/agents', '/agentic', '/samba', '/dozzle', '/media', '/notes', '/hls'];

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    host: true,
    proxy: Object.fromEntries(
      proxied.map((p) => [p, { target: LIVE, changeOrigin: true, secure: false, ws: p === '/dozzle' }]),
    ),
  },
  build: {
    sourcemap: false,
  },
});
