/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />
// Caches the app SHELL only (HTML, JS, CSS, icons) — never /api. Purpose: when opti is
// down, the installed app still opens and can say so, instead of the browser's own
// "site can't be reached". Data is always live; every value shows its own age.
import { build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;
const CACHE = `pertal-shell-${version}`;
const SHELL = [...build, ...files];

sw.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      await cache.addAll(SHELL);
      // The SPA fallback page, stored under '/' so any navigation can use it offline.
      const index = await fetch('/', { cache: 'no-store' });
      if (index.ok) await cache.put('/', index);
      await sw.skipWaiting();
    })(),
  );
});

sw.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
      await sw.clients.claim();
    })(),
  );
});

sw.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== sw.location.origin || url.pathname.startsWith('/api/')) return; // live data: never cached

  // Pages: network first (a deploy is picked up immediately), cached shell if opti is gone.
  if (req.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const res = await fetch(req, { signal: AbortSignal.timeout(5000) });
          if (res.ok) (await caches.open(CACHE)).put('/', res.clone());
          return res;
        } catch {
          return (await caches.match('/')) ?? Response.error();
        }
      })(),
    );
    return;
  }

  // Hashed build assets and static files: cache first.
  if (SHELL.includes(url.pathname)) {
    event.respondWith((async () => (await caches.match(url.pathname)) ?? fetch(req))());
  }
});
