import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
const backend = `http://127.0.0.1:${process.env.ASTRA_PORT || 3003}`;
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: Number(process.env.ASTRA_FRONTEND_PORT || 5174), strictPort: true,
    proxy: { '/api': backend, '/hls': backend, '/media/wallpapers': backend, '/astra-preview.html': backend } },
  preview: { host: '127.0.0.1', port: 5174, strictPort: true },
  build: { outDir: 'dist', sourcemap: false },
});
