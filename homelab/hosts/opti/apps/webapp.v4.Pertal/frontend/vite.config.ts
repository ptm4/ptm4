import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev only: /api goes to a local Pertal backend (`npm run dev` in ../backend, port 3100).
// Production never sees this — the built app is served by the backend itself.
const target = process.env.PERTAL_BACKEND ?? 'http://127.0.0.1:3100';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    host: true,
    proxy: { '/api': { target, changeOrigin: true } },
  },
  build: { sourcemap: false },
});
