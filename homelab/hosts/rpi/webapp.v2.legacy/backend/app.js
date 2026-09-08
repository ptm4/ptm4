// buildApp() — the whole webapp as a factory, so tests can fastify.inject() it
// without opening a port. server.js is the only caller that actually listens.
//
// Ground rules for this backend (from the 2026-08-10 redesign; each is load-bearing):
//   - Timeout ladder: every route owns its upstream timeout and they must nest inside
//     nginx's caps — 240s on /api/agents and /api/llama, 60s default elsewhere.
//     No global requestTimeout here (node default 0) for exactly that reason.
//   - /api/agents and /api/llama author real 502 JSON; nginx passes it through and
//     the frontend's self-restart/expected-disconnect logic keys on it. Never wrap
//     those errors.
//   - NO response schemas on ported routes: Fastify serializers strip undeclared
//     properties, which with a legacy client is silent data loss. (New /api/ui/*
//     routes may use full schemas — they have no legacy client.)
//   - bodyLimit 5MB: an architecture-agent fragment (full docker inspect across ~15
//     containers) runs 30-60kb, and express.json was raised for the same reason.
const fastify = require('fastify');
const cors = require('@fastify/cors');

async function buildApp(opts = {}) {
  const app = fastify({
    logger: opts.logger ?? { level: 'warn' },
    bodyLimit: 5 * 1024 * 1024,
    // NB: no ignoreTrailingSlash — it breaks @fastify/static's directory redirects
    // (infinite 301 on /architecture/, verified in the parity tests). Every v1 API
    // consumer uses exact slash-less paths, so nothing is lost.
  });

  await app.register(cors, { origin: '*' });

  // Express tolerated `Content-Type: application/json` with an EMPTY body (its parser
  // yields {}). Fastify errors on it (FST_ERR_CTP_EMPTY_JSON_BODY). No current caller
  // hits this — audited 2026-08-10, all 16 json-CT call sites in the legacy app carry
  // a body — but the shim keeps the old contract for anything not audited (curl, bots).
  app.addContentTypeParser('application/json', { parseAs: 'string' }, (req, body, done) => {
    if (body === '') return done(null, {});
    try {
      done(null, JSON.parse(body));
    } catch (e) {
      e.statusCode = 400;
      done(e, undefined);
    }
  });

  // Wallpaper uploads (the only multipart route — see routes/ui.js).
  await app.register(require('@fastify/multipart'));

  await app.register(require('./plugins/vitals-poller'));

  // Health check — useful for NGINX upstream checks. Registered before the bare-/api
  // dashboard routes so nothing can shadow it.
  app.get('/api/health', async () => ({
    status: 'ok', host: 'webapp.rpi.lan', uptime: process.uptime(),
  }));

  await app.register(require('./routes/reports'),      { prefix: '/api/reports' });
  await app.register(require('./routes/runners'),      { prefix: '/api/runners' });
  await app.register(require('./routes/weather'),      { prefix: '/api/weather' });
  // bot proxies — /api/health is taken by the webapp's own healthcheck, hence /api/healthdigest
  await app.register(require('./routes/healthdigest'), { prefix: '/api/healthdigest' });
  await app.register(require('./routes/jellyfin'),     { prefix: '/api/jellyfin' });
  await app.register(require('./routes/sports'),       { prefix: '/api/sports' });
  await app.register(require('./routes/hltv'),         { prefix: '/api/hltv' });
  await app.register(require('./routes/streams'),      { prefix: '/api/streams' });
  await app.register(require('./routes/llama'),        { prefix: '/api/llama' });
  await app.register(require('./routes/architecture'), { prefix: '/api/architecture' });
  await app.register(require('./routes/agents'),       { prefix: '/api/agents' });
  await app.register(require('./routes/uptime'),       { prefix: '/api/uptime' });
  await app.register(require('./routes/agentic'),      { prefix: '/api/agentic' });
  await app.register(require('./routes/samba'),        { prefix: '/api/samba' });
  await app.register(require('./routes/pihole'),       { prefix: '/api/pihole' });
  await app.register(require('./routes/vitals'),       { prefix: '/api/vitals' });
  // new in v2 — no legacy client, so these carry full schemas
  await app.register(require('./routes/ui'),            { prefix: '/api/ui' });
  await app.register(require('./routes/notifications'), { prefix: '/api/notifications' });
  await app.register(require('./routes/updates'),       { prefix: '/api/updates' });
  await app.register(require('./routes/hldb'),          { prefix: '/api/hldb' });
  await app.register(require('./routes/pricewatch'),    { prefix: '/api/pricewatch' });
  // dashboard read-model sits at bare /api (containers, timers, activity, trends, linkcheck)
  await app.register(require('./routes/dashboard'),    { prefix: '/api' });

  await app.register(require('./plugins/static'));

  return app;
}

module.exports = buildApp;
