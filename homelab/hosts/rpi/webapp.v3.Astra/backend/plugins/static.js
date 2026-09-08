// Every static mount in one place.
//
// Two eras coexist here:
//   - frontend/dist   — the v2 React app (Vite build, content-hashed assets). CI builds
//     it; it does not exist in a fresh checkout, and P1 deliberately ships without it.
//   - frontend-legacy — the v1 vanilla app, served VERBATIM. While dist is absent it
//     owns the root (the site looks identical to v1); once dist exists it moves to
//     /legacy/ but its standalone pages (architecture/streams/…) and root-linked
//     assets (/tokens.css etc.) keep their original URLs until each is ported.
const fs = require('fs');
const path = require('path');
const fp = require('fastify-plugin');
const fastifyStatic = require('@fastify/static');
const { LEGACY_DIR, DIST_DIR } = require('../lib/paths');
const { WALLPAPER_DIR } = require('../lib/store');

// Standalone documents still served from the legacy tree at their original paths.
const LEGACY_DIRS = ['architecture', 'agents', 'agentic', 'samba', 'streams'];

// Root-level files the standalone pages (and any stale cached HTML) link absolutely.
const LEGACY_ROOT_FILES = ['tokens.css', 'style.css', 'app.js', 'favicon.svg', 'index.html'];

module.exports = fp(async function staticMounts(app) {
  const haveDist = fs.existsSync(path.join(DIST_DIR, 'index.html'));

  // Vite content-hashes everything under assets/ — safe to cache forever. Must be
  // its own registration: a setHeaders callback gets overwritten by the plugin's
  // cache-control handling, a dedicated maxAge does not. Registered regardless of
  // the root's era; without dist the route just 404s.
  if (haveDist) {
    app.register(fastifyStatic, {
      root: path.join(DIST_DIR, 'assets'),
      prefix: '/assets/',
      decorateReply: false,
      maxAge: '1y',
      immutable: true,
    });
  }

  // Root: the v2 app when built, the untouched v1 app until then. index.html goes
  // out with the plugin's default max-age=0 (revalidate) so deploys are picked up
  // on the next load.
  app.register(fastifyStatic, {
    root: haveDist ? DIST_DIR : LEGACY_DIR,
    prefix: '/',
    index: ['index.html'],
    redirect: true,
  });

  // Uploaded wallpapers from the writable volume. Created on first upload, so the
  // dir may not exist yet — @fastify/static needs it to, hence the mkdir.
  try { fs.mkdirSync(WALLPAPER_DIR, { recursive: true }); } catch (_) { /* read-only fs in tests */ }
  if (fs.existsSync(WALLPAPER_DIR)) {
    app.register(fastifyStatic, {
      root: WALLPAPER_DIR,
      prefix: '/media/wallpapers/',
      decorateReply: false,
      maxAge: '7d',
    });
  }

  // The whole v1 SPA, always reachable — the redesign's instant visual fallback.
  app.register(fastifyStatic, {
    root: LEGACY_DIR,
    prefix: '/legacy/',
    decorateReply: false,
    index: ['index.html'],
    redirect: true,
  });
  // Bare /legacy sits outside the prefix above; relative Location, so nginx's
  // container-port trap (nginx-wg.conf) never applies.
  app.get('/legacy', (req, reply) => reply.redirect('/legacy/', 301));

  if (haveDist) {
    // Standalone legacy pages keep their original URLs. Bare /architecture (no slash)
    // would otherwise fall through to the SPA fallback, so redirect it explicitly —
    // relative Location, so nginx's container-port trap (nginx-wg.conf) never applies.
    for (const dir of LEGACY_DIRS) {
      app.register(fastifyStatic, {
        root: path.join(LEGACY_DIR, dir),
        prefix: `/${dir}/`,
        decorateReply: false,
        index: ['index.html'],
        redirect: true,
      });
      app.get(`/${dir}`, (req, reply) => reply.redirect(`/${dir}/`, 301));
    }

    // /tokens.css & friends — linked absolutely by every standalone page.
    for (const f of LEGACY_ROOT_FILES) {
      app.get(`/${f}`, (req, reply) => reply.sendFile(f, LEGACY_DIR));
    }

    // SPA fallback: any unmatched GET that wants HTML gets the v2 shell (BrowserRouter
    // owns the path). API calls and asset misses keep their JSON/plain 404.
    app.setNotFoundHandler((req, reply) => {
      const wantsHtml = (req.headers.accept || '').includes('text/html');
      if (req.method === 'GET' && wantsHtml && !req.url.startsWith('/api/')) {
        return reply.type('text/html').sendFile('index.html', DIST_DIR);
      }
      reply.code(404).send({ error: 'Not Found', path: req.url });
    });
  }
}, { name: 'static-mounts' });
