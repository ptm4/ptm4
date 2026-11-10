// Discord bot controls: a thin proxy to each discord-* container's control API on the
// internal compose network. The bots own their config; Pertal forwards and maps
// failures to JSON. Ported from v3.Fable's five per-bot route files (one table here).
//
// Mounted at the SAME paths v3 used (/api/weather, /api/sports, /api/healthdigest,
// /api/jellyfin, /api/hltv), with the same response shapes, because more than the UI
// reads them: homelab-db's ingest polls every bot's /status, and at cutover it simply
// keeps working against :8443.
//
// One deliberate difference from v3: every request that changes something (config
// save, send now, re-roll, say, profile, inbox ack) runs as a Pertal job, so it shows
// in the job tray and lands in the audit trail. Reads stay plain proxies.
//
// HLTV: the /day query (max_age default 3600, date, tz) and the timeouts are copied
// verbatim from v3's routes/hltv.js. Change them only together with that file, and
// never route any of this through Gluetun.
'use strict';

const DRY = process.env.PERTAL_ACTIONS === 'dry';
const DAY_MAX_AGE = Number(process.env.HLTV_DAY_MAX_AGE || 3600);

const BOTS = {
  weather: {
    label: 'Weather', container: 'discord-weather', base: process.env.WEATHER_BOT_URL || 'http://discord-weather:8080',
    routes: [
      { method: 'get', path: '/status', botPath: '/health' },
      { method: 'get', path: '/config', botPath: '/config' },
      { method: 'put', path: '/config', botPath: '/config', op: 'config' },
      { method: 'post', path: '/send', botPath: '/send', timeout: 30000, op: 'send' },
      { method: 'get', path: '/preview', botPath: '/preview', timeout: 30000 },
      { method: 'get', path: '/witty', botPath: '/witty' },
      { method: 'post', path: '/witty/reroll', botPath: '/witty/reroll', timeout: 30000, op: 'witty-reroll' },
      // the considered-reply lane + server profiles (discord-weather README, "Answering pings")
      { method: 'get', path: '/inbox', botPath: '/inbox' },
      { method: 'post', path: '/inbox/ack', botPath: '/inbox/ack', op: 'inbox-ack' },
      { method: 'post', path: '/say', botPath: '/say', timeout: 15000, op: 'say' },
      { method: 'post', path: '/profile', botPath: '/profile', op: 'profile' },
      { method: 'get', path: '/geocode', botPath: '/geocode', timeout: 15000, query: (q) => ({ q: String(q.q || '').trim() }), require: ['q'] },
    ],
  },
  sports: {
    label: 'Sports', container: 'discord-sports', base: process.env.SPORTS_BOT_URL || 'http://discord-sports:8080',
    routes: [
      { method: 'get', path: '/status', botPath: '/health' },
      { method: 'get', path: '/config', botPath: '/config' },
      { method: 'put', path: '/config', botPath: '/config', op: 'config' },
      { method: 'post', path: '/send', botPath: '/send', timeout: 30000, op: 'send' },
      { method: 'get', path: '/preview', botPath: '/preview', timeout: 30000 },
      { method: 'get', path: '/teams', botPath: '/teams', timeout: 20000,
        query: (q) => ({ league: String(q.league || '').trim(), q: String(q.q || '').trim() }), require: ['league', 'q'] },
    ],
  },
  healthdigest: {
    label: 'Health digest', container: 'discord-healthdigest', base: process.env.HEALTHDIGEST_BOT_URL || 'http://discord-healthdigest:8080',
    // /send and /preview may kick a fresh doctor run (~90s), hence 120s.
    routes: [
      { method: 'get', path: '/status', botPath: '/health' },
      { method: 'get', path: '/config', botPath: '/config' },
      { method: 'put', path: '/config', botPath: '/config', op: 'config' },
      { method: 'post', path: '/send', botPath: '/send', timeout: 120000, op: 'send' },
      { method: 'get', path: '/preview', botPath: '/preview', timeout: 120000 },
    ],
  },
  jellyfin: {
    label: 'Jellyfin arrivals', container: 'discord-jellyfin', base: process.env.JELLYFIN_BOT_URL || 'http://discord-jellyfin:8080',
    routes: [
      { method: 'get', path: '/status', botPath: '/health' },
      { method: 'get', path: '/config', botPath: '/config' },
      { method: 'put', path: '/config', botPath: '/config', op: 'config' },
      { method: 'post', path: '/send', botPath: '/send', timeout: 30000, op: 'send' },
      { method: 'get', path: '/preview', botPath: '/preview', timeout: 30000 },
      { method: 'get', path: '/check', botPath: '/check', timeout: 15000 },
    ],
  },
  hltv: {
    label: 'HLTV', container: 'discord-hltv', base: process.env.HLTV_BOT_URL || 'http://discord-hltv:8080',
    routes: [
      { method: 'get', path: '/status', botPath: '/health' },
      { method: 'get', path: '/config', botPath: '/config' },
      { method: 'put', path: '/config', botPath: '/config', op: 'config' },
      { method: 'post', path: '/send', botPath: '/send', timeout: 90000, op: 'send' },
      { method: 'get', path: '/preview', botPath: '/preview', timeout: 90000 },
      { method: 'get', path: '/day', botPath: '/day', timeout: 25000,
        query: (q) => ({ max_age: q.max_age ?? DAY_MAX_AGE, ...(q.date ? { date: q.date } : {}), ...(q.tz ? { tz: q.tz } : {}) }) },
      { method: 'get', path: '/vrs', botPath: '/vrs', timeout: 20000 },
    ],
  },
};

const OP_LABEL = {
  config: 'Save settings', send: 'Post now', 'witty-reroll': 'Re-roll the witty line',
  'inbox-ack': 'Mark inbox handled', say: 'Say in a channel', profile: 'Update a server profile',
};

// JSON in/out; a non-JSON error body comes back wrapped as { raw }, as in v3.
async function proxyJson(base, method, urlPath, body, timeoutMs) {
  const res = await fetch(`${base}${urlPath}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
  return { status: res.status, ok: res.ok, data };
}

function registerBot(app, key, bot) {
  return async function botRoutes(scope) {
    for (const r of bot.routes) {
      scope[r.method](r.path, async (req, reply) => {
        const q = req.query || {};
        if (r.require && r.require.some((k) => !String(q[k] || '').trim())) {
          return reply.code(400).send({ error: `missing ${r.require.map((k) => `?${k}=`).join(' or ')}` });
        }
        const qs = r.query ? new URLSearchParams(r.query(q)).toString() : '';
        const botPath = qs ? `${r.botPath}?${qs}` : r.botPath;
        const body = r.method === 'get' ? undefined : req.body;
        const timeout = r.timeout || 5000;

        if (!r.op) {
          try {
            const out = await proxyJson(bot.base, r.method.toUpperCase(), botPath, body, timeout);
            return reply.code(out.status).send(out.data);
          } catch (e) {
            return reply.code(502).send({ error: `${key} bot unreachable: ${e.message}` });
          }
        }

        // A change: one audited job, the bot's own answer passed straight back.
        const job = app.jobs.create({
          kind: `bot.${r.op}`, title: `${OP_LABEL[r.op] || r.op}: ${bot.label} bot`,
          host: 'opti', target: bot.container, resource: `opti:${bot.container}`,
          steps: [{ key: 'send', label: `${r.method.toUpperCase()} ${r.botPath} on ${bot.container}` }],
        });
        let out = null;
        try {
          await job.step('send', async (note) => {
            if (DRY) { note('dry run: not sent'); out = { status: 200, data: { ok: true, dry: true } }; return; }
            out = await proxyJson(bot.base, r.method.toUpperCase(), botPath, body, timeout);
            note(`bot answered HTTP ${out.status}`);
            if (!out.ok) throw new Error(out.data?.error || out.data?.raw || `HTTP ${out.status}`);
          });
          job.finish('ok');
        } catch (e) {
          job.finish('failed', e);
          if (!out) return reply.code(502).send({ error: `${key} bot unreachable: ${e.message}`, job: job.id });
        }
        reply.header('x-pertal-job', job.id);
        return reply.code(out.status).send(out.data);
      });
    }
  };
}

module.exports = async function bots(app) {
  // The Bots page's index: which bots exist and whether each answers.
  app.get('/api/bots', async () => {
    const list = await Promise.all(Object.entries(BOTS).map(async ([key, bot]) => {
      try {
        const out = await proxyJson(bot.base, 'GET', '/health', undefined, 4000);
        return { key, label: bot.label, container: bot.container, reachable: out.ok, health: out.data };
      } catch (e) {
        return { key, label: bot.label, container: bot.container, reachable: false, health: null, error: e.message };
      }
    }));
    return { bots: list, dry: DRY };
  });
  for (const [key, bot] of Object.entries(BOTS)) {
    await app.register(registerBot(app, key, bot), { prefix: `/api/${key}` });
  }
};

module.exports.BOTS = BOTS;
