import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev only: /api goes to a local Pertal backend (`npm run dev` in ../backend, port 3100).
// Production never sees this — the built app is served by the backend itself.
const target = process.env.PERTAL_BACKEND ?? 'http://127.0.0.1:3100';
// Asset Library files: the asset server on ptm — this machine — as nginx does in prod.
const assets = process.env.ASSET_SERVER_URL ?? 'http://192.168.1.3:8767';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    host: true,
    proxy: {
      '/api': { target, changeOrigin: true },
      // Stream video goes straight to stream-station on noblenumbat (nginx does the same in prod).
      '/hls': { target: process.env.STREAM_URL ?? 'http://192.168.1.6:8098', changeOrigin: true },
      '/asset-files': { target: assets, changeOrigin: true },
      '/asset-thumbs': { target: assets, changeOrigin: true },
    },
  },
  build: { sourcemap: false },
});
