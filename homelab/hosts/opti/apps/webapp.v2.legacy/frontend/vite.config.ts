import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// Dev server proxies /api (and the legacy/standalone paths) to the live rpi backend,
// so `npm run dev` works against real data from any LAN box without running the
// backend locally. Production never sees this — the built app is served by the
// Fastify backend itself.
const LIVE = 'https://192.168.1.10:8443';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: true,
    proxy: {
      '/api': { target: LIVE, changeOrigin: true, secure: false },
      '/legacy': { target: LIVE, changeOrigin: true, secure: false },
      '/architecture': { target: LIVE, changeOrigin: true, secure: false },
      '/streams': { target: LIVE, changeOrigin: true, secure: false },
      '/agents': { target: LIVE, changeOrigin: true, secure: false },
      '/agentic': { target: LIVE, changeOrigin: true, secure: false },
      '/samba': { target: LIVE, changeOrigin: true, secure: false },
      '/dozzle': { target: LIVE, changeOrigin: true, secure: false },
      '/media': { target: LIVE, changeOrigin: true, secure: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
