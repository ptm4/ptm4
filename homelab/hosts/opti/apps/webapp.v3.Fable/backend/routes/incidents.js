// /api/incidents — findings correlated into incidents, so 52 open notifications
// read as "opti's disk", "vaultwarden update" and "android unreachable" instead of
// a wall of lines. Nothing new is collected: the members are exactly the findings
// routes/notifications.js serves, plus homelab.db change events on the same host
// in the same window as supporting context.
//
// Correlation: one incident per (host, 30-minute bucket of the finding timestamp).
// Findings from one report run share a timestamp, so a doctor run that flags three
// things on opti becomes one incident with three items. Severity is the worst
// member's. The id is deterministic (host + bucket) so it survives restarts.
//
// State: acknowledging an incident acknowledges each member finding in the SAME
// acks.json the notification bell uses — the two views never disagree. Muting
// (until a date) is incident-level and lives in ui/incidents.json, never in acks.
const crypto = require('crypto');
const path = require('path');
const store = require('../lib/store');
const { collect, readAcks, writeAcks, sevRank } = require('../lib/findings');
const { cachedInject } = require('../lib/hldb-cache');

const MUTES_PATH = path.join(store.UI_DIR, 'incidents.json');
const BUCKET_MS = 30 * 60_000;
const CHANGE_WINDOW_MS = 6 * 3600_000;
const MAX_MUTES = 300;

const incidentId = (host, bucket) =>
  crypto.createHash('sha1').update(`${host}|${bucket}`).digest('hex').slice(0, 12);

const readMutes = () => store.readJson(MUTES_PATH) || {};
function writeMutes(m) {
  const entries = Object.entries(m).sort((a, b) => (b[1].until || '').localeCompare(a[1].until || ''));
  store.ensureDirs();
  store.writeJsonAtomic(MUTES_PATH, Object.fromEntries(entries.slice(0, MAX_MUTES)));
}

const SEV_LABEL = { 0: 'crit', 1: 'warn', 2: 'info' };

function build(changes) {
  const acks = readAcks();
  const mutes = readMutes();
  const now = Date.now();
  const groups = new Map();

  for (const f of collect()) {
    const host = f.host || 'fleet';
    const t = Date.parse(f.ts || '') || 0;
    const bucket = t ? Math.floor(t / BUCKET_MS) * BUCKET_MS : 0;
    const key = `${host}|${bucket}`;
    const g = groups.get(key) || { id: incidentId(host, bucket), host, bucket, items: [] };
    g.items.push({ ...f, acked: !!acks[f.id], acked_at: acks[f.id]?.at || null });
    groups.set(key, g);
  }

  const incidents = [];
  for (const g of groups.values()) {
    g.items.sort((a, b) => sevRank(a.severity) - sevRank(b.severity));
    const worst = g.items[0];
    const rank = sevRank(worst.severity);
    const ts = g.items.map((i) => Date.parse(i.ts || '') || 0).filter(Boolean);
    const first = ts.length ? new Date(Math.min(...ts)).toISOString() : null;
    const last = ts.length ? new Date(Math.max(...ts)).toISOString() : null;
    const mute = mutes[g.id];
    const muted = !!mute && Date.parse(mute.until || '') > now;
    const openItems = g.items.filter((i) => !i.acked).length;
    const status = muted ? 'muted' : openItems === 0 ? 'acked' : 'open';
    const related = (changes || []).filter((c) => c.host === g.host && ts.length
      && Math.abs((Date.parse(c.at || '') || 0) - Math.max(...ts)) < CHANGE_WINDOW_MS).slice(0, 6);
    const title = worst.message.length > 110 ? `${worst.message.slice(0, 107)}…` : worst.message;
    incidents.push({
      id: g.id,
      host: g.host === 'fleet' ? null : g.host,
      severity: SEV_LABEL[rank] || 'info',
      title: g.items.length > 1 ? `${title} (+${g.items.length - 1} more)` : title,
      count: g.items.length,
      open_count: openItems,
      sources: [...new Set(g.items.map((i) => i.source))],
      first_seen: first,
      last_seen: last,
      status,
      muted_until: muted ? mute.until : null,
      items: g.items,
      changes: related,
    });
  }

  const order = { open: 0, muted: 1, acked: 2 };
  const labelRank = { crit: 0, warn: 1, info: 2 };
  incidents.sort((a, b) => order[a.status] - order[b.status]
    || labelRank[a.severity] - labelRank[b.severity]
    || (Date.parse(b.last_seen || '') || 0) - (Date.parse(a.last_seen || '') || 0));

  return {
    incidents,
    open: incidents.filter((i) => i.status === 'open').length,
    muted: incidents.filter((i) => i.status === 'muted').length,
    acked: incidents.filter((i) => i.status === 'acked').length,
    generated_at: new Date().toISOString(),
  };
}

module.exports = async function incidentRoutes(app) {
  async function recentChanges() {
    const r = await cachedInject(app, '/api/hldb/changes?days=7');
    return r.status === 200 && Array.isArray(r.data?.events) ? r.data.events : [];
  }

  // GET /api/incidents?all=1 — open + muted by default; all=1 includes acked ones.
  app.get('/', async (req) => {
    const doc = build(await recentChanges());
    if (req.query.all !== '1') doc.incidents = doc.incidents.filter((i) => i.status !== 'acked');
    return doc;
  });

  app.get('/:id', async (req, reply) => {
    const doc = build(await recentChanges());
    const inc = doc.incidents.find((i) => i.id === req.params.id);
    if (!inc) return reply.code(404).send({ error: `no incident '${req.params.id}'` });
    return inc;
  });

  // POST /api/incidents/:id/ack {acked?: bool} — (un)acknowledge every member finding.
  app.post('/:id/ack', {
    schema: {
      params: { type: 'object', properties: { id: { type: 'string', pattern: '^[a-f0-9]{12}$' } } },
      body: { type: 'object', properties: { acked: { type: 'boolean' } } },
    },
  }, async (req, reply) => {
    const doc = build([]);
    const inc = doc.incidents.find((i) => i.id === req.params.id);
    if (!inc) return reply.code(404).send({ error: `no incident '${req.params.id}'` });
    const acks = readAcks();
    const acked = req.body?.acked !== false;
    const at = new Date().toISOString();
    for (const item of inc.items) {
      if (acked) acks[item.id] = { at };
      else delete acks[item.id];
    }
    writeAcks(acks);
    if (app.events) {
      const all = collect();
      app.events.emit('notifications', { unacked: all.filter((n) => !acks[n.id]).length, total: all.length });
      app.events.emit('incidents', { id: inc.id, status: acked ? 'acked' : 'open' });
    }
    return { ok: true, id: inc.id, acked, items: inc.items.length };
  });

  // POST /api/incidents/:id/mute {days?: number, until?: ISO, clear?: bool}
  app.post('/:id/mute', {
    schema: {
      params: { type: 'object', properties: { id: { type: 'string', pattern: '^[a-f0-9]{12}$' } } },
      body: {
        type: 'object',
        properties: {
          days: { type: 'number', minimum: 0.01, maximum: 365 },
          until: { type: 'string' },
          clear: { type: 'boolean' },
        },
      },
    },
  }, async (req, reply) => {
    const mutes = readMutes();
    const id = req.params.id;
    if (req.body?.clear) {
      delete mutes[id];
      writeMutes(mutes);
      if (app.events) app.events.emit('incidents', { id, status: 'open' });
      return { ok: true, id, muted_until: null };
    }
    let until = null;
    if (req.body?.until) {
      const t = Date.parse(req.body.until);
      if (Number.isNaN(t)) return reply.code(400).send({ error: 'until must be an ISO date' });
      until = new Date(t).toISOString();
    } else {
      const days = req.body?.days ?? 7;
      until = new Date(Date.now() + days * 86400_000).toISOString();
    }
    mutes[id] = { until, at: new Date().toISOString() };
    writeMutes(mutes);
    if (app.events) app.events.emit('incidents', { id, status: 'muted', muted_until: until });
    return { ok: true, id, muted_until: until };
  });
};
