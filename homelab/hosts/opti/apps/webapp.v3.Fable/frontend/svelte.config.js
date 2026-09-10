import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// SPA mode: every route renders client-side, the backend's static plugin serves
// dist/index.html for any unmatched HTML GET (backend/plugins/static.js). No SSR — the
// app only ever runs behind the Fastify server, which has no Node SSR runtime.
/** @type {import('@sveltejs/kit').Config} */
export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: 'dist',
      assets: 'dist',
      fallback: 'index.html',
      precompress: false,
      strict: true,
    }),
    // Keep hashed assets under /_app/immutable/ — static.js mounts that path with a
    // 1y immutable cache (the v2 equivalent was /assets/).
    appDir: '_app',
  },
};
