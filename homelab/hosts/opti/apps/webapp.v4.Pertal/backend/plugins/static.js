// Serves the built SvelteKit SPA from frontend/dist. Unknown non-API GETs get
// index.html (client-side routing). Hashed assets under /_app/immutable are cached for
// a year; index.html is never cached, so a deploy is picked up on the next load.
'use strict';
const fs = require('fs');
const path = require('path');
const fp = require('fastify-plugin');
const { DIST_DIR } = require('../lib/paths');

module.exports = fp(async function staticPlugin(app) {
  const indexPath = path.join(DIST_DIR, 'index.html');
  const hasDist = fs.existsSync(indexPath);

  if (hasDist) {
    await app.register(require('@fastify/static'), {
      root: DIST_DIR,
      prefix: '/',
      wildcard: false,
      index: false,
      cacheControl: false, // otherwise @fastify/static's max-age=0 overrides setHeaders below
      setHeaders: (res, filePath) => {
        if (filePath.includes(`${path.sep}_app${path.sep}immutable${path.sep}`)) {
          res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
        } else {
          res.setHeader('Cache-Control', 'no-cache');
        }
      },
    });
  }

  app.setNotFoundHandler((req, reply) => {
    if (req.method !== 'GET' || req.url.startsWith('/api/')) {
      return reply.code(404).send({ error: 'not found' });
    }
    if (!hasDist) {
      return reply.type('text/html').send('<!doctype html><title>Pertal</title><p>Pertal backend is running; the frontend is not built (frontend/dist missing).</p>');
    }
    reply.header('Cache-Control', 'no-cache');
    return reply.type('text/html').send(fs.readFileSync(indexPath));
  });
}, { name: 'pertal-static' });
