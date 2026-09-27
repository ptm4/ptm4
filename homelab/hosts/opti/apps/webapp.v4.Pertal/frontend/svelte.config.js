import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// SPA: the Fastify backend serves dist/index.html for every non-API route.
/** @type {import('@sveltejs/kit').Config} */
export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ pages: 'dist', assets: 'dist', fallback: 'index.html', precompress: false, strict: true }),
    appDir: '_app',
  },
};
